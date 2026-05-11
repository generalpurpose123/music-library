import os
import dataclasses


class MusicFile:
    def __init__(self,
                 file_path: str):
        self.file_path = file_path

    @property
    def file_name(self):
        return os.path.basename(self.file_path)
