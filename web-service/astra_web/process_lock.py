"""OS-held singleton lock; a process crash releases it without deleting evidence."""
import os


class ProcessLock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.file = open(self.path, 'a+b')
        try:
            self.file.seek(0)
            if self.file.read(1) == b'':
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('Another Astra server already owns this data directory. Run one worker.')
        return self

    def __exit__(self, *args):
        self.file.close()
