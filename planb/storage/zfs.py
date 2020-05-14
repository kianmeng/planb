from contextlib import contextmanager
import logging
import os.path
import time

from django.core.exceptions import ImproperlyConfigured

from planb.common.subprocess2 import CalledProcessError, check_output

from .base import Datasets, Dataset, DatasetNotFound, Storage

# Check if we can backup (daily)
# backup
# Rotate snapshots
# - daily
# - weekly
# - monthly
# - yearly
# create snapshot
# - daily
# - weekly
# - monthly
# - yearly
# Shoot completed flag into monitoring

logger = logging.getLogger(__name__)


class PerformCommands:
    @classmethod
    def ensure_defaults(cls, config):
        super().ensure_defaults(config)
        config.setdefault('BINARY', '/sbin/zfs')
        config.setdefault('SUDOBIN', '/usr/bin/sudo')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__perform_system_binary = self.config['BINARY']
        self.__perform_sudo_binary = self.config['SUDOBIN']

    def __perform_system_command(self, cmd):
        """
        Do exec command, expect 0 return value, convert output to utf-8.
        """
        try:
            output = check_output(cmd)
        except CalledProcessError as e:
            logger.info('Non-zero exit after cmd {!r}: {}'.format(
                cmd, e))
            raise
        return output.decode('utf-8')  # expect valid ascii/utf-8

    def _perform_sudo_command(self, cmd):
        """
        Do __perform_system_command, but with 'sudo'.
        """
        return self.__perform_system_command(
            (self.__perform_sudo_binary,) + tuple(cmd))

    def _perform_binary_command(self, cmd):
        """
        Do _perform_sudo_command, but for the supplied binary.
        """
        return self._perform_sudo_command(
            (self.__perform_system_binary,) + tuple(cmd))


class ZfsStorage(PerformCommands, Storage):
    @classmethod
    def ensure_defaults(cls, config):
        super().ensure_defaults(config)
        if 'POOLNAME' not in config:
            raise ImproperlyConfigured('Zfs storage requires a POOLNAME')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.poolname = self.config['POOLNAME']

    def zfs_get_local_path(self, dataset_name):
        # FIXME: this is yet another zfs_get_properties()
        cmd = ('get', '-Ho', 'value', 'mountpoint', dataset_name)
        try:
            out = self._perform_binary_command(cmd).rstrip('\r\n')
        except CalledProcessError as e:
            logging.warning(
                'Error while calling: %r, %s', cmd, e.output.strip())
            out = None
        return out

    def zfs_get_properties(
            self, dataset_name, keys, snapname=None):
        if snapname is not None:
            dataset_name = '{}@{}'.format(dataset_name, snapname)
        property_names = ','.join(keys)
        cmd = (
            'get', '-Hpo', 'value', property_names, dataset_name)
        try:
            values = self._perform_binary_command(cmd)  # LF-separated
        except CalledProcessError as e:
            logger.warning(
                'Error while calling: %r, %s', cmd, e.output.strip())
            values = '0\n' * len(keys)  # YUCK.. odd default
        else:
            output = values.split('\n')
            assert len(output) == len(keys) + 1, (keys, repr(output))
            output = [i.strip() for i in output[0:-1]]

        return output

    def zfs_get_used_size(self, dataset_name):
        return int(self.zfs_get_properties(dataset_name, keys=('used',))[0])

    def zfs_get_referenced_size(self, dataset_name, snapname=None):
        return int(self.zfs_get_properties(
            dataset_name, keys=('referenced',), snapname=snapname)[0])

    def zfs_create(self, dataset_name):
        # For multi-slash paths, we may need to create parents as well.
        parts = dataset_name.split('/')
        for idx, last_part in enumerate(parts):
            part = '/'.join(parts[0:(idx + 1)])
            try:
                cmd = ('get', '-o', 'value', '-Hp', 'type', part)
                type_ = self._perform_binary_command(cmd).rstrip('\r\n')
            except CalledProcessError:
                # Does not exist. Create it.
                self._perform_binary_command(('create', part))
                self._perform_binary_command(('set', 'canmount=noauto', part))
            else:
                assert type_ == 'filesystem', (dataset_name, part, type_)

        # After mount, make it ours. Blegh. Unfortunate side-effect of
        # using sudo for the ZFS create.
        try:
            self.zfs_mount(dataset_name)
        except CalledProcessError:
            pass  # already mounted (we hope?)
        path = self.zfs_get_local_path(dataset_name)
        self._perform_sudo_command(('chown', str(os.getuid()), path))

        # Log something.
        logger.info('Created ZFS dataset: %s', dataset_name)

    def zfs_mount(self, dataset_name):
        # Even if we have user-powers on /dev/zfs, we still cannot call
        # all commands.
        # $ /sbin/zfs mount tank/BACKUP/example-example
        # mount: only root can use "--options" option
        # cannot mount 'tank/BACKUP/example-example': Invalid argument
        # Might as well use sudo everywhere then.
        self._perform_binary_command(('mount', dataset_name))

    def zfs_unmount(self, dataset_name):
        self._perform_binary_command(('unmount', dataset_name))

    def zfs_rename_dataset(self, old_dataset_name, new_dataset_name):
        self._perform_binary_command(
            ('rename', old_dataset_name, new_dataset_name))

    # (old style)

    def snapshot_create(self, dataset_name, snapname):
        snapshot_name = '{}@{}'.format(dataset_name, snapname)
        cmd = ('snapshot', snapshot_name)
        self._perform_binary_command(cmd)
        logger.info('Created ZFS snapshot: %s', snapshot_name)
        return snapshot_name

    def snapshot_delete(self, dataset_name, snapname):
        cmd = ('destroy', '{}@{}'.format(dataset_name, snapname))
        self._perform_binary_command(cmd)

    def snapshot_list(self, dataset_name):
        cmd = (
            'list', '-d', '1', '-H', '-t', 'snapshot', '-o', 'name',
            dataset_name)
        try:
            out = self._perform_binary_command(cmd)
        except CalledProcessError as e:
            # planb.common.subprocess2.CalledProcessError:
            # /usr/bin/sudo: "cannot open 'poolX/datasetY': dataset does
            # not exist" (exit 1)
            if b'dataset does not exist' in e.errput:
                raise DatasetNotFound()
            raise

        if not out:
            return []

        snapshots = []
        for snapshot in out.split('\n'):
            if '@' in snapshot:
                # Do not include the dataset in the snapshot name.
                snapshots.append(snapshot.split('@', 1)[1])
        return snapshots

    def get_label(self):
        used, available = [
            int(i) for i in self.zfs_get_properties(
                self.poolname, keys=('used', 'available'))]

        if used and available:
            pct = '{pct:.0f}%'.format(pct=(100 * (used / (used + available))))
            available = int(available / 1024 / 1024 / 1024)
        else:
            available = pct = '???'

        return '{}, {}G free ({} used)'.format(self.name, available, pct)

    def get_datasets(self, parent=None):
        parent = self.poolname if parent is None else parent
        output = self._perform_binary_command((
            'list', '-d', '1', '-t', 'filesystem,volume',
            '-Hpo', 'name,used,type,planb:contains',
            parent))

        datasets = Datasets()
        for line in output.rstrip().split('\n'):
            dataset_name, used, type_, contains = line.split('\t')
            if dataset_name == parent:
                continue

            assert dataset_name.startswith(parent), (dataset_name, parent)
            dataset = ZfsDataset(storage=self, name=dataset_name)
            dataset.set_dataset_type(type_, contains)
            dataset.set_disk_usage(int(used))
            datasets.append(dataset)

        return datasets

    def get_dataset(self, dataset_name):
        return ZfsDataset(storage=self, name=dataset_name)

    def name_dataset(self, namespace, name):
        return '{}/{}-{}'.format(self.poolname, namespace, name)


class ZfsDataset(Dataset):
    # TODO/FIXME: check these methods and add them as NotImplemented to the
    # base

    def has_child_datasets(self):
        if not hasattr(self, '_dataset_type'):
            self.set_dataset_type()
        return self._dataset_type == ('filesystem', 'filesystems')

    def get_child_datasets(self):
        return self._storage.get_datasets(self.name)

    def flush(self):
        super().flush()

        if hasattr(self, '_dataset_type'):
            del self._dataset_type

    def ensure_exists(self):
        # Common case is the unmounted yet existing path. If the mount point
        # exists, everything in it should be fine too.
        if self.get_mount_path():
            return

        # Try creating it. (Creation also mounts it.)
        self._storage.zfs_create(self.name)

        # Now it should exist. Create the 'data' subdirectory as well.
        if hasattr(self, '_get_mount_path'):
            del self._get_mount_path
        if hasattr(self, '_get_data_path'):
            del self._get_data_path

        path = self.get_data_path()
        os.makedirs(path, 0o700)

        # Unmount if possible.
        try:
            self._storage.zfs_unmount(self.name)
        except CalledProcessError:
            pass

    def set_dataset_type(self, type=None, contains=None):
        if type is None and contains is None:
            type, contains = self._storage.zfs_get_properties(
                self.name, keys=('type', 'planb:contains'))

        # planb:contains used to be unset, defaults to 'data'
        if contains == '-':
            contains = 'data'

        assert type in ('filesystem', 'volume'), (self.name, type)
        assert contains in (
            'data',         # a regular filesystem inside
            'filesystems',  # subdirectories (individually synced)
            # 'zvols',      # ...
        ), 'Unexpected planb:contains {!r} for {!r}'.format(
            contains, self.name)

        self._dataset_type = (type, contains)

    @contextmanager
    def workon(self, data_path=None):
        cwd = os.getcwd()
        try:
            os.chdir('/')
            self.begin_work(data_path)
            yield
        finally:
            self.end_work()
            os.chdir(cwd)

    def begin_work(self, data_path=None):
        assert os.getcwd() == '/', os.getcwd()

        # The path we want to be in should be a subdirectory of the mount
        # point. Otherwise we cannot be sure that we have it locked.
        path = data_path or self.get_data_path()
        assert path.startswith(self.get_mount_path() + '/'), path

        # Try mounting a few times. There could be someone unmounting it just
        # now.
        for attempt in (1, 2, 3):
            try:
                # Attempt mount.
                self._storage.zfs_mount(self.name)  # zfs dataset
            except CalledProcessError:
                # Maybe it was already mounted?
                pass

            try:
                # Quickly jump into it. If it was already mounted, or we
                # mounted it just now, this should succeed.
                os.chdir(path)
            except FileNotFoundError:
                # Wait a bit before retrying.
                time.sleep(5)
            else:
                # Success!
                break
        else:
            # No luck after the Nth attempt. Fail.
            raise ValueError('Failed to work on {!r} ({})'.format(
                path, self.name))  # FIXME: better exception

    def end_work(self):
        # Leave directory, so it can be unmounted.
        os.chdir('/')
        try:
            self._storage.zfs_unmount(self.name)  # zfs dataset
        except CalledProcessError:
            # Ok. This might be because someone else is using it. Ignore.
            pass

        # Note that the mount point directory stays, but it will be
        # empty/unmounted (and owned by root) at this point.
        assert os.getcwd() == '/', os.getcwd()

    def get_mount_path(self):
        if not hasattr(self, '_get_mount_path'):
            ret = self._storage.zfs_get_local_path(self.name)
            if not ret:
                return None  # no negative cache

            self._get_mount_path = ret
        return self._get_mount_path

    def get_data_path(self):
        if not hasattr(self, '_get_data_path'):
            local_path = self.get_mount_path()
            if not local_path:
                raise ValueError(
                    'path {!r} for {!r} does not exist'.format(
                        local_path, self.name))
            self._get_data_path = os.path.join(local_path, 'data')
        return self._get_data_path

    def get_snapshot_path(self, snapshot):
        '''
        Return the path to the hidden snapshot directory.
        '''
        return os.path.abspath(os.path.join(
            self.get_data_path(), '../.zfs/snapshot', snapshot, 'data'))

    def get_used_size(self):
        return self._storage.zfs_get_used_size(self.name)

    def get_referenced_size(self, snapname=None):
        return self._storage.zfs_get_referenced_size(
            self.name, snapname)

    def rename_dataset(self, new_dataset_name):
        # Cannot rename while working from the dataset directory.
        # zfs rename will force a unmount/remount sequence for the filesystem
        # and any descendent file systems.
        assert not os.getcwd().startswith(self.get_mount_path()), (
            'Cannot rename dataset {} while working from dataset directory '
            '{}'.format(self.get_mount_path(), os.getcwd()))

        self._storage.zfs_rename_dataset(self.name, new_dataset_name)
        self.name = new_dataset_name

        # Clear cached properties.
        if hasattr(self, '_get_mount_path'):
            del self._get_mount_path
        if hasattr(self, '_get_data_path'):
            del self._get_data_path
