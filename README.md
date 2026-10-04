# HoYo wallpaper downloads

This repo stores some wallpapers downloaded from the official HoYoLAB collection. You can find the downloaded wallpapers in 2560x1440-size in the folder `2560x1440/`. You can also modify one line of the code to extract other wallpaper sizes.

You may find the source from website [HoYoLAB - Genshin Impact Wallpapers Collection](https://www.hoyolab.com/creatorCollection/526679).

`download.py` takes short links such as `https://hoyo.link/...`, downloads each wallpaper zip, and copies out every image whose filename matches `2560.+1440.+` (for example `2560x1440.jpg`).

Python 3 is enough. The script uses only the standard library.

## Add a link

Put one link per line in `links.txt`. A series title after the URL is optional and becomes part of the filename:

```
https://hoyo.link/xxxxxxxx Series Title
```

`hoyo.link/xxxxxxxx` works too. Then run:

```
python download.py
```

Passing links on the command line does the same thing. New links are appended to `links.txt`, then the zip is downloaded and the 2560×1440 images are extracted:

```
python download.py https://hoyo.link/xxxxxxxx
python download.py --title "Series Title" https://hoyo.link/xxxxxxxx
python download.py https://hoyo.link/aaa https://hoyo.link/bbb
```

Run the script again whenever you add more lines. Zips and images that are already saved are left as they are.

The title is used when a zip is saved for the first time. Put it on the line, or pass `--title`, before the first download if you want it in the filename.

## Where files go

- `links.txt` — the links to fetch. The original set is already listed here.
- `wallpapers/` — the zip archives
- `2560x1440/` — the 2560×1440 images
- `manifest.json` — remembers each finished link so it is not requested again

Zip names look like `2026-08-31 Everwinter Without Mercy.zip`. The date comes from the download URL. Each image keeps that name and adds the folder it came from inside the zip, for example `2026-08-31 Everwinter Without Mercy - 1.jpg`.

A series often includes more than one wallpaper, so the folder number (`1`, `2`, `kv1`, and so on) is part of the image name. One official zip stored a file as `2560x1440..jpg`, with an extra dot. That file matches and is extracted too.

If a zip has no matching image, the archive is still kept and the script says so.
