# -*- coding: utf-8 -*-
"""应用版本号——唯一来源。

为什么单独一个文件：版本号必须在三个地方完全一致，否则「检查更新」会永久说谎。

1. `app/main.py` 的 `FastAPI(version=...)` 与 `/api/app/version` 返回给前端的值；
2. GitHub Release 的 tag（`v1.0.1` 里的 `1.0.1`）；
3. PyInstaller 打出来的包（它只是把本文件原样打包，不需要额外注入）。

只改 tag 不改这里 → 新版本装好之后仍然认为自己旧，每次打开都提示更新；
只改这里不改 tag → Release 上查到的版本号对不上，同样永久提示。

CI 的 `release.yml` 里有一道闸门：tag 去掉 `v` 后必须与本文件 `VERSION` 相等，
不等就让发布失败。改版本号时请同步改这里和 tag。
"""

VERSION = "1.0.4"
