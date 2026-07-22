from __future__ import annotations

import ctypes
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class UnsafeManifestPath(Exception):
    """An opened handle did not retain the approved local path identity."""


class ManifestReadFailure(Exception):
    """The manifest could not be opened as a regular file."""


class ManifestTooLarge(Exception):
    """The manifest exceeds the configured byte bound."""


@dataclass(frozen=True, slots=True)
class ApprovedDirectory:
    path: Path
    device: int
    inode: int


class ManifestFilesystem(Protocol):
    def read_manifest(
        self, approved: ApprovedDirectory, maximum_bytes: int
    ) -> bytes: ...


class SecureManifestFilesystem:
    """Read manifest.json without following a replaceable path after approval."""

    def read_manifest(self, approved: ApprovedDirectory, maximum_bytes: int) -> bytes:
        if os.name == "nt":
            return self._read_windows(approved, maximum_bytes)
        return self._read_posix(approved, maximum_bytes)

    @staticmethod
    def _read_windows(approved: ApprovedDirectory, maximum_bytes: int) -> bytes:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        generic_read = 0x80000000
        share_read_write = 0x00000001 | 0x00000002
        open_existing = 3
        backup_semantics = 0x02000000
        open_reparse_point = 0x00200000
        invalid_handle = ctypes.c_void_p(-1).value
        reparse_attribute = 0x00000400
        directory_attribute = 0x00000010

        class HandleInfo(ctypes.Structure):
            _fields_ = [
                ("dwFileAttributes", wintypes.DWORD),
                ("ftCreationTime", wintypes.FILETIME),
                ("ftLastAccessTime", wintypes.FILETIME),
                ("ftLastWriteTime", wintypes.FILETIME),
                ("dwVolumeSerialNumber", wintypes.DWORD),
                ("nFileSizeHigh", wintypes.DWORD),
                ("nFileSizeLow", wintypes.DWORD),
                ("nNumberOfLinks", wintypes.DWORD),
                ("nFileIndexHigh", wintypes.DWORD),
                ("nFileIndexLow", wintypes.DWORD),
            ]

        get_info = kernel32.GetFileInformationByHandle
        get_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(HandleInfo))
        get_info.restype = wintypes.BOOL
        get_final_path = kernel32.GetFinalPathNameByHandleW
        get_final_path.argtypes = (
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        get_final_path.restype = wintypes.DWORD

        def open_handle(path: Path, access: int, flags: int):
            handle = create_file(
                str(path),
                access,
                share_read_write,
                None,
                open_existing,
                flags,
                None,
            )
            if handle == invalid_handle:
                raise ManifestReadFailure
            return handle

        def handle_info(handle) -> HandleInfo:
            info = HandleInfo()
            if not get_info(handle, ctypes.byref(info)):
                raise UnsafeManifestPath
            return info

        def handle_path(handle) -> Path:
            buffer = ctypes.create_unicode_buffer(32768)
            length = get_final_path(handle, buffer, len(buffer), 0)
            if not length or length >= len(buffer):
                raise UnsafeManifestPath
            value = buffer.value
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
            return Path(value)

        def same_path(left: Path, right: Path) -> bool:
            return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
                os.path.abspath(right)
            )

        directory_handle = open_handle(
            approved.path, 0, backup_semantics | open_reparse_point
        )
        try:
            directory_info = handle_info(directory_handle)
            directory_inode = (
                directory_info.nFileIndexHigh << 32
            ) | directory_info.nFileIndexLow
            if (
                directory_info.dwFileAttributes & reparse_attribute
                or not directory_info.dwFileAttributes & directory_attribute
                or directory_inode != approved.inode
                or not same_path(handle_path(directory_handle), approved.path)
            ):
                raise UnsafeManifestPath

            manifest_path = approved.path / "manifest.json"
            manifest_handle = open_handle(
                manifest_path, generic_read, open_reparse_point
            )
            try:
                manifest_info = handle_info(manifest_handle)
                if (
                    manifest_info.dwFileAttributes & reparse_attribute
                    or manifest_info.dwFileAttributes & directory_attribute
                    or not same_path(handle_path(manifest_handle), manifest_path)
                ):
                    raise UnsafeManifestPath
                size = (manifest_info.nFileSizeHigh << 32) | manifest_info.nFileSizeLow
                if size > maximum_bytes:
                    raise ManifestTooLarge
                read_file = kernel32.ReadFile
                read_file.argtypes = (
                    wintypes.HANDLE,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                    wintypes.LPVOID,
                )
                read_file.restype = wintypes.BOOL
                remaining = size
                chunks: list[bytes] = []
                while remaining:
                    chunk_size = min(remaining, 64 * 1024)
                    buffer = ctypes.create_string_buffer(chunk_size)
                    count = wintypes.DWORD()
                    if not read_file(
                        manifest_handle,
                        buffer,
                        chunk_size,
                        ctypes.byref(count),
                        None,
                    ):
                        raise ManifestReadFailure
                    if count.value == 0:
                        raise ManifestReadFailure
                    chunks.append(buffer.raw[: count.value])
                    remaining -= count.value
                return b"".join(chunks)
            finally:
                close_handle(manifest_handle)
        finally:
            close_handle(directory_handle)

    @staticmethod
    def _read_posix(approved: ApprovedDirectory, maximum_bytes: int) -> bytes:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory_flag = getattr(os, "O_DIRECTORY", None)
        if no_follow is None or directory_flag is None:
            raise UnsafeManifestPath
        current_fd: int | None = None
        try:
            parts = approved.path.parts
            current_fd = os.open(parts[0], os.O_RDONLY | directory_flag | no_follow)
            for component in parts[1:]:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | directory_flag | no_follow,
                    dir_fd=current_fd,
                )
                os.close(current_fd)
                current_fd = next_fd
            directory_info = os.fstat(current_fd)
            if (
                directory_info.st_dev != approved.device
                or directory_info.st_ino != approved.inode
            ):
                raise UnsafeManifestPath
            manifest_fd = os.open(
                "manifest.json", os.O_RDONLY | no_follow, dir_fd=current_fd
            )
            try:
                manifest_info = os.fstat(manifest_fd)
                if not stat.S_ISREG(manifest_info.st_mode):
                    raise UnsafeManifestPath
                if manifest_info.st_size > maximum_bytes:
                    raise ManifestTooLarge
                result = bytearray()
                while len(result) <= maximum_bytes:
                    chunk = os.read(
                        manifest_fd, min(64 * 1024, maximum_bytes + 1 - len(result))
                    )
                    if not chunk:
                        break
                    result.extend(chunk)
                if len(result) > maximum_bytes:
                    raise ManifestTooLarge
                return bytes(result)
            finally:
                os.close(manifest_fd)
        except (ManifestTooLarge, UnsafeManifestPath):
            raise
        except OSError:
            raise ManifestReadFailure from None
        finally:
            if current_fd is not None:
                os.close(current_fd)


DEFAULT_MANIFEST_FILESYSTEM = SecureManifestFilesystem()
