# f26-14_Bench-Top_Low-field_MRI

## MaRCoS Environment setup
The MaRCoS Wiki has many tutorials for setup, though some are outdated/unclear. Below are instructions on how to replicate the team's working setup:
### Tutorial 1 (https://github.com/vnegnev/marcos_extras/wiki/tut_set_up_marcos_software)
Follow the tutorial, but a good-known setup for PC is:
* Ubuntu 22.04 WSL
* Python 3.10.12
* NumPy 1.21.5
* msgpack 1.0.3
* GCC 11.4.0
* CMake 3.27.9
* Verilator 4.106

Also switch the branches for the following repos:
* marcos_client: 35b9066 (origin/master) or origin/mimo
* marcos_server: 9dc1a81
* marga:         5bddc13 (origin/master)

### Essential libraries in `marcos_pack`
* marcos_client
* marcos_server
* marcos_extras
* marga
* marga_pulseq

## Running sequences
explain the osii_marcos_tse code pack & how it interfaces with premade OSII system(Nexus) to be MaRCoS-compatible.

## Image Reconstruction
