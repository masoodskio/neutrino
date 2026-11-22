# neutrino
Small, Fast and Modular PS2 Device Emulator

## Design
A neutrino is a particle with almost zero mass, and that's what this device emulator's primary goal is. To have almost 0 mass when emulating devices to maximize compatibility.

Neutrino also does not have a user interface, instead it's meant to be integrated as a backend to a frontend (user interface). This makes neutrino much more easy to maintain, and allows many more applications to be made using neutrino as the backend.

With neutrino all modules are... modular. They are in a separate folder called `modules`. This allows the user add new and improved modules. What modules are loaded is fully configurable using TOML config files in the `config` folder.

## Environments
An environment in neutrino describes what IOP modules are loaded and defines what features the environment has. In neutrino there are 3 environments:
- Boot Environment (BE): environment neutrino is loaded from (by uLE / ps2link / ...), containing neutrino, configuration files and drivers
- Load Environment (LE): neutrino's loader.elf reboots into the LE, containing virtual disk images
- Emulation Environment (EE): neutrino's ee_core.elf reboots into the EE, emulating devices

## Backing Store Driver (BSD)
A backing store driver provides a storage location for storing virtual disk images. For instance of DVD's, HDD's or MC's.
The following backing storage devices are supported:
Device             | PS2 model  | Speed                                                                            | Device comp.                       | Type         | BSD
-------------------|------------|----------------------------------------------------------------------------------|------------------------------------|--------------|----------
USB                | FAT + 70k  |![x](https://progress-bar.xyz/750?scale=2200&suffix=KB/s&&progress_color=d9534f)  | ![x](https://progress-bar.xyz/80)  | Block Device | `usb`
USB                | slim       |![x](https://progress-bar.xyz/900?scale=2200&suffix=KB/s)                         | ![x](https://progress-bar.xyz/80)  | Block Device | `usb`
MX4SIO             | slim       |![x](https://progress-bar.xyz/1150?scale=2200&suffix=KB/s)                        | ![x](https://progress-bar.xyz/60)  | Block Device | `mx4sio`
MMCE               | slim       |![x](https://progress-bar.xyz/1350?scale=2200&suffix=KB/s)                        | ![x](https://progress-bar.xyz/100) | File System  | `mmce`
MX4SIO             | FAT + 70k  |![x](https://progress-bar.xyz/1500?scale=2200&suffix=KB/s)                        | ![x](https://progress-bar.xyz/60)  | Block Device | `mx4sio`
MMCE               | FAT + 70k  |![x](https://progress-bar.xyz/1700?scale=2200&suffix=KB/s)                        | ![x](https://progress-bar.xyz/100) | File System  | `mmce`
iLink / IEEE1394   | FAT        |![x](https://progress-bar.xyz/6?scale=2&suffix=MB/s)                              | ![x](https://progress-bar.xyz/10)  | Block Device | `ilink`
UDPBD              | ALL        |![x](https://progress-bar.xyz/10?scale=2&suffix=MB/s)                             | ![x](https://progress-bar.xyz/100) | Block Device | `udpbd`
UDPFS              | ALL        |![x](https://progress-bar.xyz/10?scale=2&suffix=MB/s)                             | ![x](https://progress-bar.xyz/100) | File System  | `udpfs`
SMB (read-only)    | ALL        | not measured on a PS2                                                            | ![x](https://progress-bar.xyz/100) | File System  | `smb`
NFS (read-only)    | ALL        | not measured on a PS2                                                            | ![x](https://progress-bar.xyz/100) | File System  | `nfs`
ATA (internal HDD) | FAT        |![x](https://progress-bar.xyz/30?scale=2&suffix=MB/s)                             | ![x](https://progress-bar.xyz/100) | Block Device | `ata`

Clarifying information:

- **PS2 model**: The older FAT PS2 models and the first slim PS2 model (70k) have the original PS1 MIPS R3000 CPU. Later slim PS2 models have a new CPU with 'DECKARD' emulating the MIPS R3000. This is why there is a speed difference between those two groups of PS2 models.

- **Speed**: USB, MX4SIO and MMCE have been tested with neutrino v1.5.0. The other speeds are based on older tests and should serve as an indication. For proper emulation of the ps2 DVD drive a speed of at least 2.2MB/s is needed. The slower the speed, the more likely video's will stutter. Due to game-bugs, some games will not even run if the device is too slow.

- **Device comp.**: how many devices will work with neutrino. For instance most USB sticks work, but some (mostly USB3.0 sticks) don't work. With mx4sio, many SD cards are not compatible, etc... Don't hold these values for fact, they are based on my personal observations and should give you an indication on what devices would fit your need.

- **Type**: How the device exposes itself to the PS2: as a file system with files that can be opened/closed read and written. Or as a block device with 512byte sectors.

- **BSD**: Name of the BSD for use with the neutrino command line, such as: `-bsd=ilink`

### Block devices
For block devices the PS2 will use it's own filesystem and partition drivers.

The following partitioning schemes are supported:
- MBR (Master Boot Record)
- GPT (GUID Partition Table)

The following file systems are supported:
- FAT32, accessable as `mass:<file>.iso`
- exFat, accessable as `mass:<file>.iso`
- HDLoader, accessable as `hdl:<file>`, `hdl:<file>.iso`, `hdl:<part>` or `hdl:<part>.iso`

Note that the HDLoader backing store is currently read-ony, and limited to only emulating the DVD.

### Block device fragmentation
During load neutrino will request all 'fragments' where virtual disk images are located. After rebooting into the Emulation Environment there is no more file system available, instead neutrino will access the sectors of the block device directly using a fragment table. A **maximum of 64 fragments** is supported for the combined total of the virtual disk images you need. If for instance you have 1 virtual DVD and 1 virtual MC (that's already 2 fragments), then they cannot have more than 64 fragments combined. If your (FAT32/exFat) drive is more fragmented you'll need to de-fragment your drive (details not covered here).

Note that this limitation only applies to the "block device" type, and not the "file system" type, even though it can be the uSD card. MX4SIO for instance is used as a block device with the 64 fragment limitation. But when inserting the same exFat formatted uSD card into an MMCE device, this limitation does not exist, becouse the CPU on MMCE device will completely handle the exFat filesystem.

## CD/DVD emulation
The following CD/DVD emulation drivers are supported:
- No: using original CD's / DVD's in the optical drive
- ESR: using ESR patched DVD's in the optical drive
- File: using an iso file from the backing store

## ATA HDD emulation
The following HDD emulation drivers are supported:
- No: using ATA HDD in the PS2
- File: using a virtual HDD image file from the backing store

## Usage instructions
Neutrino is a command line application. To get the most out of neutrino you will need to run it from the command line, for instance using [ps2link](https://github.com/ps2dev/ps2link) and [ps2client](https://github.com/ps2dev/ps2client).

Alternatively you can use a more user friendly GUI from one of the third-party projects (see below), but with a limited feature set.

Command line usage instructions:

```
Usage: neutrino.elf options

Options:
  -bsd=<driver>     Backing store drivers (optional, auto-detected from path prefix), supported are:
                    - no     (uses cdvd)
                    - ata    (block device)
                    - usb    (block device)
                    - mx4sio (block device)
                    - udpbd  (block device)
                    - udpfs  (file system)
                    - ilink  (block device)
                    - mmce   (file system)
                    - smb    (file system, read-only)
                    - nfs    (file system, read-only)

  -bsdfs=<driver>   Backing store fileystem drivers used for block device, supported are:
                    - exfat (default)
                    - hdl   (HD Loader)
                    - bd    (Block Device)
                    NOTE: Used only for block devices (see -bsd)

  -dvd=<mode>       DVD emulation mode, supported are:
                    - no (default)
                    - esr
                    - <file>

  -ata0=<mode>      ATA HDD 0 emulation mode, supported are:
                    - no (default)
                    - <file>
                    NOTE: only both emulated, or both real.
                          mixing not possible
  -ata0id=<mode>    ATA 0 HDD ID emulation mode, supported are:
                    - no (default)
                    - <file>
                    NOTE: only supported if ata0 is present
  -ata1=<mode>      See -ata0=<mode>

  -mc0=<mode>       MC0 emulation mode, supported are:
                    - no (default)
                    - <file>
  -mc1=<mode>       See -mc0=<mode>

  -elf=<file>       ELF file to boot, supported are:
                    - auto (elf file from cd/dvd) (default)
                    - <file>

  -gc=<compat>      Game compatibility modes, supported are:
                    - 0: IOP: Fast reads (sceCdRead)
                    - 1: dummy
                    - 2: IOP: Sync reads (sceCdRead)
                    - 3: EE : Unhook syscalls
                    - 5: IOP: Emulate DVD-DL
                    - 7: IOP: Fix game buffer overrun
                    Multiple options possible, for example -gc=23

  -gsm=v:c          GS video mode

                    Parameter v = Force video mode to:
                    -         : don't force (default)  (480i/576i)
                    - fp1     : force 240p/288p - auto PAL/NTSC
                    - fp2     : force 480p/576p - auto PAL/NTSC
                    - 1080ix1 : force 1080i width x1, height x1 (very small!)
                    - 1080ix2 : force 1080i width x2, height x2
                    - 1080ix3 : force 1080i width x3, height x3

                    Parameter c = Compatibility mode:
                    -      : no compatibility mode (default)
                    - 1    : field flipping type 1 (GSM/OPL)
                    - 2    : field flipping type 2
                    - 3    : field flipping type 3

                    Examples:
                    -gsm=fp2      - recommended mode
                    -gsm=fp2:1    - recommended mode, with compatibility 1
                    -gsm=1080ix2

  -cwd=<path>       Change working directory

  -cfg=<file>       Load extra user/game specific config file (without .toml extension)

  -dbc              Enable debug colors
  -logo             Enable logo (adds rom0:PS2LOGO to arguments)
  -qb               Quick-Boot directly into load environment

  --b               Break, all following parameters are passed to the ELF

Usage examples:
  neutrino.elf -dvd=usb:path/to/filename.iso
  neutrino.elf -dvd=mx4sio:path/to/filename.iso
  neutrino.elf -dvd=mmce:path/to/filename.iso
  neutrino.elf -dvd=ilink:path/to/filename.iso
  neutrino.elf -dvd=udpbd:path/to/filename.iso
  neutrino.elf -dvd=udpfs:path/to/filename.iso
  neutrino.elf -dvd=smb:path/to/filename.iso
  neutrino.elf -dvd=nfs:path/to/filename.iso
  neutrino.elf -dvd=ata:path/to/filename.iso
  neutrino.elf -bsd=ata -bsdfs=hdl -dvd=hdl:filename.iso
  neutrino.elf -bsd=udpbd -bsdfs=bd -dvd=bdfs:udp0p0
```

## SMB

`-dvd=smb:path/to/filename.iso` plays a game from a share on an SMB2
file server, over the network adapter. It uses
[usmb2](https://github.com/sahlberg/usmb2), a minimal SMB2 client with its
own tiny TCP/IP stack. Only DVD images are supported: the driver is
read-only, so it cannot hold HDD or memory card images.

The network, server and login are module arguments in
`config/bsd-smb.toml`, the same for `smb_ioman.irx` and `smb_fhi.irx`, and
the PS2's address also goes in `ministack.irx`'s arguments:

```toml
args = ["ip=192.168.1.10", "mask=255.255.255.0", "gw=192.168.1.1", "srv=192.168.1.2", "user=guest", "pass=", "share=PS2SMB"]
```

- `ip`, `mask`, `gw`: the PS2's address, netmask and gateway
- `srv`: the address of the SMB server
- `user`, `pass`: NTLM login
- `share`: the name of the share; the path is relative to it

## NFS

`-dvd=nfs:path/to/filename.iso` plays a game from an NFS export, over the
network adapter. It uses [unfs4](https://github.com/sahlberg/unfs4), a
minimal NFSv4.0 client, on the same tiny TCP/IP stack as SMB. Only DVD
images are supported: the driver is read-only, so it cannot hold HDD or
memory card images.

The network, server and export are module arguments in
`config/bsd-nfs.toml`, the same for `nfs_ioman.irx` and `nfs_fhi.irx`, and
the PS2's address also goes in `ministack.irx`'s arguments:

```toml
args = ["ip=192.168.1.10", "mask=255.255.255.0", "gw=192.168.1.1", "srv=192.168.1.2", "export=/srv/ps2"]
```

- `ip`, `mask`, `gw`: the PS2's address, netmask and gateway
- `srv`: the address of the NFS server
- `export`: the exported directory; the path is relative to it
- `uid`, `gid`: the AUTH_SYS credentials, 0 if not given. With the usual
  root squash that is the anonymous user, so the images must be readable
  by everyone.

The server must have NFSv4.0 enabled. The PS2 connects from a port below
1024, so the export does not need the `insecure` option. On Linux:

```
/srv/ps2  192.168.1.0/24(ro)
```

## UDPFS / UDPBD PC Server

The `pc/udpfs_server.py` script serves files and/or block devices to the PS2 over UDP (Ethernet).

### Requirements

- **Python 3** (no additional packages required for basic use)
- **`lz4`** — optional, required only for `.zso` (LZ4-compressed ISO) support:
  ```
  pip install lz4
  ```
- **`libchdr0`** — required for `.chd` (CHD compressed ISO) support:
  ```
  apt install libchdr0
  ```
  Build from source: https://github.com/rtissera/libchdr

The `pc/compressed_iso/` directory is a local module bundled with the server; no installation is needed.

### Usage

```
# Share a USB drive (or any block device) with many games — typical UDPBD use case
python pc/udpfs_server.py -b /dev/sdX          # Linux
python pc/udpfs_server.py -b \\.\PhysicalDriveX  # Windows

# Share a single disk image (UDPBD mode)
python pc/udpfs_server.py -b game.iso

# Share a directory as a filesystem (UDPFS mode)
python pc/udpfs_server.py -d /path/to/ps2games

# Share both a block device and a directory
python pc/udpfs_server.py -b /dev/sdX -d /path/to/ps2games

# With transparent decompression (.iso is appended to .zso/.cso/.chd names)
python pc/udpfs_server.py -d /games --enable-compression

# Read-only mode
python pc/udpfs_server.py -b /dev/sdX --read-only
```

### Compression support

When `--enable-compression` is passed, the server transparently decompresses compressed ISO images:

Format | Extension | Compression          | Extra dependency
-------|-----------|----------------------|----------------
ZSO    | `.zso`    | LZ4                  | `pip install lz4`
CSO    | `.cso`    | zlib                 | none
CHD    | `.chd`    | zlib/lzma/huff/flac  | `apt install libchdr0`

## Online play (experimental, UDPFS only)

This branch has experimental online-play support while loading a game over UDPFS. The storage driver and the game's network stack share the PS2's Ethernet adapter through INET/EENET shims. This is not a general compatibility guarantee, and this online-play setup supports UDPFS only.

### Download and install for a normal UDPFS launcher

This is the setup used with a normal UDPFS frontend launch, such as the tested NHDDL setup. It does not require custom `-bsd=udpfs-net` launch arguments.

1. Open this repository's GitHub Actions page, select a successful `CI-compile` run for the `udpfs-online-identity-clean` branch, and download its build artifact. Extract the artifact and the release `.7z` inside it. Do not use the source-code ZIP as the installation package.
2. Back up your working frontend/Neutrino installation, including `neutrino.elf`, `modules/`, `config/`, and your memory-card network profiles. Keep your frontend executable and settings.
3. Copy the archive's `neutrino.elf` and matching files from `modules/` into the active installation used by your frontend, for example `APPS/NHDDL/`. Keep files from the same build together; replacing the executable alone does not update external modules. The set must include `smap.irx`, `ministack.irx`, `udpfs_ioman.irx`, `udpfs_fhi.irx`, `smap_inet.irx`, `smap_eenet.irx`, and `ee_core.elf`, plus the other supplied dependencies.
4. Copy the archive's `config/bsd-udpfs-net.toml` into the installation's `config/` directory, but name the installed copy `bsd-udpfs.toml`, replacing the old file only after backing it up:

   ```text
   Archive:    config/bsd-udpfs-net.toml
   Install as: APPS/NHDDL/config/bsd-udpfs.toml
   ```

   Use your frontend's actual active configuration directory if it differs from this example. Merely placing `bsd-udpfs-net.toml` beside the ordinary file does not enable online support for a normal UDPFS launch.
5. In the installed `bsd-udpfs.toml`, reapply your working `ministack.irx` IP arguments and any other required local customizations from the backup. For a new installation, set an appropriate PS2 storage-stack IP as described below. Do not overwrite your entire configuration directory with defaults. Make sure the supplied `config/i_dev9_ns.toml` is available, along with its module dependencies; the online configuration uses `depends = ["i_dev9_ns"]`.
6. Start the PC server, fully restart the PS2, and launch your UDPFS game normally through the frontend as described below. No changes to your saved network profile are required just to install the build.

The active `bsd-udpfs.toml` must contain both shim module entries:

```toml
[[module]]
file = "smap_inet.irx"
env = ["EE"]

[[module]]
file = "smap_eenet.irx"
env = ["EE"]
```

It must not contain a `[[fake]]` block whose `file` is `ENT_SMAP.IRX`; the EENET shim must intercept that module instead. Keep unrelated fake-module entries. The CI build prepares the online configuration in the artifact. The repository's unprocessed TOML template may still contain the older fake entry, so use the successful build artifact rather than copying the raw source template.

This filename replacement enables the experimental online module set for ordinary UDPFS launches in that installation. To undo it, restore your backed-up configuration and matching working binaries.

### Start the UDPFS server and configure networking

On the PC, share the directory containing your game images:

```sh
python pc/udpfs_server.py -d /path/to/ps2games
```

In the release archive, the script is under `udpfs_server/` instead of `pc/`; for example, from the extracted release directory run:

```sh
python udpfs_server/udpfs_server.py -d /path/to/ps2games
```

Python 3 is required; use `python3` instead of `python` if that is its name on your PC. Keep the bundled `compressed_iso/` directory beside the server script and leave the server running while playing. Allow its UDP traffic through the PC firewall on your trusted local network, and make sure the PS2 can reach the PC. Do not expose the file server to the public internet.

In the active `config/bsd-udpfs.toml`, retain or set the PS2 storage stack's address in the `ministack.irx` entry:

```toml
[[module]]
file = "ministack.irx"
args = ["ip=192.168.1.10"]
env = ["LE", "EE"]
```

`192.168.1.10` is only an example, not a required address and not the PC server's address. Use an appropriate address for your LAN, avoid conflicts with other devices, and preserve known-working IP settings when upgrading. The game's saved network profile is configured separately; editing this TOML does not update the profile's IP, gateway, or DNS settings.

For online play, the game's network path also needs access to its supported server. A direct PS2-to-PC connection that can serve an ISO does not by itself provide internet access; use a suitable LAN/router connection or an already-working PC routing/sharing setup.

### Launch and connect

After installing the online configuration as `bsd-udpfs.toml`, select and start the game through your frontend's normal UDPFS launch. The equivalent basic command is:

```sh
neutrino.elf -dvd="udpfs:DVD/Game.iso"
```

The example path is relative to the server's shared directory: `/path/to/ps2games/DVD/Game.iso` on the PC becomes `udpfs:DVD/Game.iso` on the PS2. Ordinary UDPFS selection loads `bsd-udpfs.toml`, which is why the filename replacement above is required for this method.

Fully restart the PS2 after changing binaries. Boot the game, select a working memory-card network profile, and follow the game's community-server instructions for any required game-specific settings or patches. This feature does not restore a discontinued server by itself. Keep an existing working profile; if testing a new profile, save it separately instead of overwriting the working one.

### Alternative: explicit online backend selection

If you control the launch arguments, you can leave the online configuration named `config/bsd-udpfs-net.toml` and select it explicitly instead of replacing `bsd-udpfs.toml`:

```sh
neutrino.elf -bsd=udpfs-net -dvd="udpfs:DVD/Game.iso"
```

For this alternative only, put your IP settings in `bsd-udpfs-net.toml`. Use one method consistently: normal UDPFS launch with the online configuration installed as `bsd-udpfs.toml`, or explicit `-bsd=udpfs-net` with `bsd-udpfs-net.toml`. The explicit flag is not needed for the normal-launcher instructions above.

### Experimental status and known limitations

- An earlier development build (`111254b`) reached the lobby and joined a match in Star Wars Battlefront II v1.01 (`SLUS_212.40`) over UDPFS using an existing `SCE/Ethernet` profile. This is a limited hardware test, not certification of every subsequent build or every game.
- Network setup can still show a greyed-out `SCE/SMAP` entry. Device identity/profile matching remains under investigation; do not delete a working profile merely to remove that entry. Ratchet & Clank online compatibility is not confirmed.
- Stop/unload and repeated network-stack entry are not fully supported. Restart the console between failed attempts rather than relying on repeated online-menu re-entry.
- UDPFS disc reads and game packets share Ethernet and IOP resources. Heavy reads can cause contention; sustained gameplay performance has not been comprehensively measured.
- Keep a known-working backup and report the build commit, game ID/version, frontend, and whether failure occurs during boot, network setup, login, or gameplay. Do not publish passwords or other private network credentials.

## Third-Party Loaders
The following third-party projects use neutrino:

Loader | Author
-|-
[XEB+ neutrino Launcher Plugin](https://github.com/sync-on-luma/xebplus-neutrino-loader-plugin) | sync-on-luma
[NHDDL](https://github.com/pcm720/nhddl) | pcm720
[RETROLauncher](https://github.com/Spaghetticode-Boon-Tobias/RETROLauncher) | Boon Tobias
[OSD-XMB](https://github.com/HiroTex/OSD-XMB) | Hiro Tex
[PSBBN](https://github.com/CosmicScale/PSBBN-Definitive-English-Patch) + [BBNL](https://github.com/pcm720/bbnl) | CosmicScale + pcm720
[RiptOPL](https://github.com/NathanNeurotic/Open-PS2-Loader) | NathanNeurotic
[wOPL](https://github.com/ps2homebrew/wOPL) | KrahJohlito
[Modulo](https://github.com/AdityaKumar7209/Modulo-R1-Beta-Preview---PS2) | AdityaKumar7209

Add your project here? Send me a PR.
