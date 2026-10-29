# 发布目录说明

发布工具和模板保留在本目录根部，生成的部署包、校验文件和部署说明按规范版本归档到对应版本目录。

当前源码版本为 `v4.5`，最新部署包位于 `release/artifacts/v4.5/`。目录中已有的
`v0.3.0-alpha.*` 产物属于历史部署物，仅用于追溯，不能作为当前版本部署包。

修改版本元数据后，先运行：

```bash
python release/check_version.py
```

推荐的未来产物命名方式：

```text
release/artifacts/v4.5/nicokara-cloud-v4.5-<shortsha>-<buildtime>.tar.gz
release/artifacts/v4.5/deploy-nicokara-cloud-v4.5-<shortsha>-<buildtime>.sh
release/artifacts/v4.5/部署说明-v4.5-<shortsha>-<buildtime>.md
```

SSH 面板已有 `/data/nicokara` 部署时，最简升级命令为：

```bash
curl -fsSL -H 'Accept: application/vnd.github.raw' \
  'https://api.github.com/repos/delete039/nicokara-cloud/contents/release/install-latest.sh?ref=main' | sudo bash
```

也可以通过环境变量覆盖网站地址和产物地址：

```bash
curl -fsSL -H 'Accept: application/vnd.github.raw' \
  'https://api.github.com/repos/delete039/nicokara-cloud/contents/release/install-latest.sh?ref=main' | \
  sudo env NICOKARA_RELEASE_BASE_URL=https://api.github.com/repos/delete039/nicokara-cloud/contents/release/artifacts/v4.5 \
  bash -s -- https://your-domain.example
```
