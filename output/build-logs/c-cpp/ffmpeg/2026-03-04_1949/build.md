# Build Log — ffmpeg

**Date:** 2026-03-04T20:02:39.819859
**Status:** SUCCESS
**Duration:** 744.4 seconds

## Repository

- **URL:** https://github.com/FFmpeg/FFmpeg.git
- **Branch:** master
- **Description:** Multimedia framework (~1.2M LoC, 20+ third-party libs)

## Build Steps

1. `./configure --enable-gpl --enable-nonfree --enable-shared --disable-static --enable-libx264 --enable-libx265 --enable-libvpx --enable-libopus --enable-libmp3lame --enable-libfdk-aac --enable-libfreetype --enable-libfontconfig --enable-libfribidi --enable-libass --enable-openssl`
2. `make -j1`

## Instrumentation

- **Tracer:** bomtrace3
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `ffmpeg`
- `ffprobe`
- `libavcodec/libavcodec.so`
- `libavformat/libavformat.so`
- `libavutil/libavutil.so`
- `libswscale/libswscale.so`
