#!/usr/bin/env python3



from pathlib import Path
from pathvalidate import sanitize_filename
import sys,os
import time
import subprocess
import fire
import shlex
from typing import List



class Bfg:


	def __init__(s, sshstr=''):
		s._sshstr = sshstr
		if sshstr == '':
			s._remote_str = '(here)'
		else:
			s._remote_str = '(on the other machine)'
		s._local_str = '(here)'
		s._sudo = ['sudo']
		

	def commit_and_push_and_checkout(s, FS_ROOT_MOUNT_POINT=None, SUBVOLUME='/', REMOTE_SUBVOLUME='/bfg', PARENTS:List[str]=None):
		"""
		Snapshot your data, "btrfs send"/"btrfs receive" the snapshot to the other machine, and checkout it there

		:param FS_ROOT_MOUNT_POINT: mount point of SUBVOLUME filesystem
		:param SUBVOLUME: your data
		:param REMOTE_SUBVOLUME: desired filesystem path of your data on the other machine
		:return: filesystem path of the snapshot created on the other machine
		"""
		remote_snapshot_path = s.commit_and_push(FS_ROOT_MOUNT_POINT, SUBVOLUME, REMOTE_SUBVOLUME, PARENTS)
		s.checkout_remote(remote_snapshot_path, REMOTE_SUBVOLUME)
		return REMOTE_SUBVOLUME

	
	def commit_and_generate_patch(s, SUBVOLUME='/', PATCH_FILE_DIR='/', PARENTS:List[str]=None):
		"""

		:param SUBVOLUME:
		:param PATCH_FILE_DIR:
		:param PARENTS:
		:return:
		"""
		snapshot = s.commit(SUBVOLUME)
		#print(Path(snapshot).parts[-2:])
		fn = PATCH_FILE_DIR + '/' + '__'.join(Path(snapshot).parts[-2:])
		#print(fn)
		s._send(snapshot, ' > ' + fn, PARENTS)
		_prerr(f'DONE, generated patch from {snapshot} into {fn}')
		return fn

		

	def commit_and_push(s, FS_ROOT_MOUNT_POINT=None, SUBVOLUME='/', REMOTE_SUBVOLUME='/bfg', PARENTS:List[str]=None):
		snapshot = s.commit(SUBVOLUME)
		return s.push(FS_ROOT_MOUNT_POINT, SUBVOLUME, snapshot, REMOTE_SUBVOLUME, PARENTS)
		

	def checkout_local(s, SNAPSHOT, SUBVOLUME):
		"""stash your SUBVOLUME, and replace it with SNAPSHOT"""
		stash_local(SUBVOLUME)
		s._local_cmd(f'btrfs subvolume snapshot {SNAPSHOT} {SUBVOLUME}')
		_prerr(f'DONE {s._local_str}, checked out {SNAPSHOT} into {SUBVOLUME}')
		return SUBVOLUME


	def checkout_remote(s, SNAPSHOT, SUBVOLUME):
		"""ssh into the other machine,
		stash your SUBVOLUME, and replace it with SNAPSHOT"""
		s.stash_remote(SUBVOLUME)
		s._remote_cmd(f'btrfs subvolume snapshot {SNAPSHOT} {SUBVOLUME}')
		_prerr(f'DONE {s._remote_str}, checked out {SNAPSHOT} into {SUBVOLUME}')
		return SUBVOLUME
		

	def stash_local(s, SUBVOLUME):
		"""snapshot and delete your SUBVOLUME"""
		snapshot = s.local_make_ro_snapshot(SUBVOLUME, s.calculate_snapshot_path(SUBVOLUME, 'stash_before_local_checkout'))
		s._local_cmd(f'btrfs subvolume delete {SUBVOLUME}')
		_prerr(f'DONE {s._local_str}, snapshotted {SUBVOLUME} into {snapshot}, and deleted it.')
		return snapshot

	def stash_remote(s, SUBVOLUME):
		"""snapshot and delete your SUBVOLUME"""
		if s._remote_cmd(['ls', SUBVOLUME], die_on_error=False) == -1:
			_prerr(f'nothing to stash {s._remote_str}, {SUBVOLUME} doesn\'t exist.')
			return None
		else:
			snapshot = s.remote_make_ro_snapshot(SUBVOLUME, s.calculate_snapshot_path(Path(SUBVOLUME), 'stash_before_remote_checkout'))
			s._remote_cmd(f'btrfs subvolume delete {SUBVOLUME}')
			_prerr(f'DONE {s._remote_str}, snapshotted {SUBVOLUME} into {snapshot}, and deleted it.')
			return snapshot
		

	def local_make_ro_snapshot(s, VOL, SNAPSHOT):
		"""make a read-only snapshot of VOL into SNAPSHOT, locally"""
		SNAPSHOT_PARENT = os.path.split((SNAPSHOT))[0]
		s._local_cmd(f'mkdir -p {SNAPSHOT_PARENT}')
		s._local_cmd(f'btrfs subvolume snapshot -r {VOL} {SNAPSHOT}')
		_prerr(f'DONE {s._local_str}, snapshotted {VOL} into {SNAPSHOT}')
		return SNAPSHOT

	def remote_make_ro_snapshot(s, VOL, SNAPSHOT):
		"""make a read-only snapshot of VOL into SNAPSHOT, remotely"""
		SNAPSHOT_PARENT = os.path.split((SNAPSHOT))[0]
		s._remote_cmd(f'mkdir -p {SNAPSHOT_PARENT}')
		s._remote_cmd(f'btrfs subvolume snapshot -r {VOL} {SNAPSHOT}')
		_prerr(f'DONE {s._remote_str}, snapshotted {VOL} into {SNAPSHOT}')
		return SNAPSHOT


	def commit(s, VOL='/', SNAPSHOTS_CONTAINER=None, TAG=None, SNAPSHOT=None):
		"""
		come up with a filesystem path for a snapshot, and snapshot VOL.
		"""
		VOL = Path(VOL).absolute()
		if SNAPSHOT is not None:
			SNAPSHOT = Path(SNAPSHOT).absolute()
		else:
			SNAPSHOT = s.calculate_snapshot_path(VOL, TAG)
		s.local_make_ro_snapshot(VOL, SNAPSHOT)
		return (SNAPSHOT)

				
	def push(s, FS_ROOT_MOUNT_POINT, SUBVOLUME, SNAPSHOT, REMOTE_SUBVOLUME, PARENTS=None):
		"""
		
		try to figure out shared parents, if not provided.
		subvolume is probably not needed and fs_root_mount_point can be used?
		
		"""
		if FS_ROOT_MOUNT_POINT is None:
			FS_ROOT_MOUNT_POINT = SUBVOLUME
		snapshot_parent = s.calculate_snapshot_parent_dir(Path(REMOTE_SUBVOLUME))
		s._remote_cmd(['mkdir', '-p', str(snapshot_parent)])

		if PARENTS is None:
			PARENTS = []
			for p in s.find_common_parents(FS_ROOT_MOUNT_POINT, SUBVOLUME, str(snapshot_parent)):
				PARENTS.append(p)
		PARENTS = s._filter_out_wrong_parents(SNAPSHOT, PARENTS)

		s._send(SNAPSHOT, ' | ' + s._sshstr + ' ' + s._sudo[0] + " btrfs receive " + str(snapshot_parent), PARENTS)
		_prerr(f'DONE, pushed {SNAPSHOT} into {snapshot_parent}')
		return str(snapshot_parent) + '/' + Path(SNAPSHOT).parts[-1]


	def _send(s, SNAPSHOT, target, PARENTS):
		parents_args = []
		for p in PARENTS:
			parents_args.append('-c')
			parents_args.append(p)

		cmd = shlex.join(s._sudo + ['btrfs', 'send'] + parents_args + [SNAPSHOT]) + target
		_prerr((cmd) + ' ...')
		subprocess.check_call(cmd, shell=True)


	def _filter_out_wrong_parents(s, snapshot, parents):
		"""filter out parents that aren't usable for snapshot"""
		parents2 = parents[:]
		counter = 0
		for p in parents:
			cmd = s._sudo + ['btrfs', 'send', '-c', p, snapshot]
			print(shlex.join(cmd) + ' ...')
			proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

			if s._read_first_bytes(proc.stdout) != 0:
				proc.kill()
				continue
			
			stderr = b''
			while True:
				r = proc.stderr.read(100000)
				stderr += r
				if len(r) == 0:
					break
					
			proc.kill()
			
			print(str(stderr))
			print('ok..')

			if b'\nERROR: parent determination failed for ' in stderr:
				parents2.remove(p)
				counter += 1
			else:
				print(stderr)

		
		_prerr(f'filtered out {counter} unsuitable parents')
		return parents2
		
		
	def _read_first_bytes(s, stdout):
		result = b''
		while True:
			o = stdout.read(10)
			result += o
			if len(o) == 0:
				break
			if len(result) > 10:
				break
		return len(result)
		



	def find_common_parents(s, fs_root_mount_point='/', subvolume='/', remote_subvolume='/'):
		
		remote_subvols = _get_ro_subvolumes(s._remote_cmd, remote_subvolume)
		local_subvols = _get_ro_subvolumes(s._local_cmd, subvolume)
		
		#print('remote_subvols:')
		#print(remote_subvols)
		#print('local_subvols:')
		#print(local_subvols)
		#print("common_parents:")
		
		common_parents = []
		for k,v in local_subvols.items():
			if k in remote_subvols:
				abspath = fs_root_mount_point + '/' + s._local_cmd(['btrfs', 'ins', 'sub', v, subvolume]).strip()
				common_parents.append(abspath)
		
		#print(common_parents)
		return common_parents
		
		
	def _remote_cmd(s, cmd, die_on_error=True):
		if not isinstance(cmd, list):
			cmd = shlex.split(cmd)
		if s._sshstr != '':
			ssh = shlex.split(s._sshstr)
			cmd2 = ssh + s._sudo + cmd
			_prerr(cmd2)
			return s._cmd(cmd2, die_on_error)
		else: 
			return s._local_cmd(cmd, die_on_error)


	def _local_cmd(s, c, die_on_error=True):
		if not isinstance(c, list):
			c = shlex.split(c)
		c = s._sudo + c
		_prerr(shlex.join(c) + ' ...')
		return s._cmd(c, die_on_error)

	
	def _cmd(s, c, die_on_error):
		try:
			return subprocess.check_output(c, text=True)
		except Exception as e:
			if die_on_error:
				_prerr(e)
				exit(1)
			else:
				return -1

 
	def calculate_snapshot_parent_dir(s, VOL):
		"""
		VOL: your subvolume (for example /data).
		Calculate the default snapshot parent dir. In the filesystem tree, it is on the same level as your subvolume, for example /.bfg_snapshots.data.
		"""
		return Path(str(VOL.parent) + '/.bfg_snapshots.' + VOL.parts[-1]).absolute()


	def calculate_snapshot_path(s, VOL, TAG):
		"""
		calculate the filesystem path where a snapshot should go, given a subvolume and a tag
		"""
		parent = s.calculate_snapshot_parent_dir(VOL)
		
		tss = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
		#tss = subprocess.check_output(['date', '-u', "+%Y-%m-%d_%H-%M-%S"], text=True).strip()
		ts = sanitize_filename(tss.replace(' ', '_'))

		if TAG is None:
			TAG = 'from_' + subprocess.check_output(['hostname'], text=True).strip()

		return str(Path(str(parent) + '/' + ts + '_' + TAG))


def _prerr(*a):
	print(*a, file = sys.stderr)
 


def _get_ro_subvolumes(command_runner, subvolume):
	snapshots = {}
	
	# todo: limit this to snapshots of the subvolume we want to send, at least on the sending side, otherwise, we are giving 'btrfs send' -c's that are unrelated to the given subvolume
	
	# also, what if a snapshot is snapshotted again (two hops), does it retain received-uuid?	
	
	
	for line in command_runner(['btrfs', 'subvolume', 'list', '-t', '-r', '-R', '-u', subvolume]).splitlines()[2:]:
		#_prerr(line)
		items = line.split()
		received_uuid = items[3]
		local_uuid = items[4]
		subvol_id = items[0]
		if received_uuid != '-':
			snapshots[received_uuid] = subvol_id
		if local_uuid != '-':
			snapshots[local_uuid] = subvol_id
	return snapshots




if __name__ == '__main__':
        fire.Fire(Bfg)

