# Protocol URI Guide

## URI Formats

| Protocol | Example |
|---|---|
| Local (Windows) | `C:\Users\Neil\media` |
| Local (Linux/macOS) | `/mnt/nas/media` |
| SMB | `smb://neil:pass@192.168.1.100/media/movies` |
| NFS | `nfs://192.168.1.100/volume1/media/movies` |

## SMB Details

- Uses SMB2/3 via `smbprotocol` library
- Auth: `smb://domain\\user:pass@host/share/path`
- Reads in 1MB chunks (saturates SMB3 multi-channel)
- Encrypt: set `SMB_ENCRYPT=true` for SMB3 encryption
- Share discovery: `nas_list_smb_shares("192.168.1.100", "admin", "pass")`

## NFS Details

- Mounts via OS (`mount -t nfs` on Linux, `mount_nfs` on macOS)
- Default: read-only (`NFS_READONLY=true`) — safe for cataloguing
- Linux mount opts: `noatime,nodiratime,rsize=1048576,wsize=1048576`
- macOS mount opts: `resvport,rsize=1048576,noatime`
- Requires NFS client installed on host machine

## Synology-Specific

Synology NAS exposes SMB and NFS simultaneously.

**Recommended for cataloguing:**
```
smb://admin:pass@192.168.1.100/media
```

**Recommended for high-throughput scan (Linux host):**
```
nfs://192.168.1.100/volume1/media
```

**Download Station API:**
- Auth via DSM session (SYNO.API.Auth v3)
- Destination must be an absolute path on the NAS volume
- Default TV: `/volume1/downloads/tv`
- Default Movies: `/volume1/downloads/movies`
