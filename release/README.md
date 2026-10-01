# 发布目录说明

发布工具和模板保留在本目录根部，生成的部署包、校验文件和部署说明按规范版本归档到对应版本目录。

当前源码版本为 `v4.1`，但本次版本整理不生成新的部署包。目录中已有的 `v0.3.0-alpha.*` 产物属于历史部署物，不能仅通过改文件名伪装成 `v4.1`；需要发布新包时重新运行 `package_release.py`。

修改版本元数据后，先运行：

```bash
python release/check_version.py
```

推荐的未来产物命名方式：

```text
release/artifacts/v4.1/nicokara-cloud-v4.1-<shortsha>-<buildtime>.tar.gz
release/artifacts/v4.1/deploy-nicokara-cloud-v4.1-<shortsha>-<buildtime>.sh
release/artifacts/v4.1/部署说明-v4.1-<shortsha>-<buildtime>.md
```
