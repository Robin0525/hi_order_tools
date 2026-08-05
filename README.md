# hipersonalization订单处理助手 v0.13 by Robin+Codex

这是一个面向 HiPersonalization seller 的 Windows 桌面工具。用户创建一次订单、选择一次 Product / Definition / Type / Type Option 后，可以一次选择多张本地图片；程序会逐张调用网站表单，完成原本需要重复操作的添加产品和图片上传流程。

## 当前版本

`v0.13` 包含：

- Seller 账号登录和权限验证；登录后从首页自动发现 `list-my-orders`。
- 支持保存多个 Seller 账号并通过下拉列表切换。
- 密码保存在 Windows Credential Manager，不写入账号列表或数据库。
- 启动时自动登录上次成功使用的账号。
- 创建 Order Title，并自动解析新 Order ID。
- 按 Product SKU 搜索产品。
- 实时读取 Product、Definition、Product Type 和 Type Option。
- Product 和 Definition 仅显示 ID、NAME、SKU；选择 Definition 后自动读取 Product Types。
- 一次选择多张图片，逐张提交到同一订单。
- 每张图片可以独立选择 Type Option、填写 Quantity 和 Code 后缀。
- 每张图片显示低内存缩略图，点击后按需打开较大预览。
- 缩略图使用独立列；Type Option 下拉菜单会展开到足够宽，并提供完整内容悬浮提示。
- 每张图片可标记为背面，自动给 Order Product Code 添加 `BACK_` 前缀。
- 可以把相同的 Type Option 和 Quantity 一键应用到全部图片。
- Order Product Code 默认使用 Order Title；备注支持英文、数字、空格及半角 `_ - = +`，后缀 `A001` 会生成 `_A001`。
- 一批图片全部成功后，可以继续向同一 Order 添加另一个 SKU。
- 需要创建另一张订单时，点击“开始新 Order”即可解锁并清空 Order Title 和 SKU。
- 即使正在自动登录或读取网页，关闭主窗口也会结束本工具的后台进程，不再持续占用 EXE 文件。
- Seller 登录区由所有业务功能共用；订单提交和订单确认使用独立分页。
- 创建订单区域将“开始新 Order”放在最左侧，Order ID 放在 Order Title 前方。
- 网站配置区域按 Product、Definition、Product Type 三行展示，每行包含对应下拉框和下一步读取按钮。
- 单张失败不影响后续图片。
- 使用本地 SQLite 记录结果；再次提交时自动跳过已经成功的图片。
- 图片大小上限预检查（80 MB）。
- 从网站读取 Order 列表，并可按 Order ID、Title 或 Status 筛选。
- 读取目标 Order 的全部设计、产品状态、Type Option 和 Quantity。
- 首张待确认设计上传 Shipping Stamp PDF、Stamp Type 和可选 Gift Message PDF。
- 自动逐个 Submit 该 Order 的其余设计，最终回查订单是否变为 `all_confirmed`。
- 中途失败后可安全重试：检测到已有 `image_confirmed` 设计时，不会重复上传 Shipping Stamp。
- 订单确认下拉列表显示网站现成的小缩略图；没有任何设计图的 Order 明确标记为“无设计图”。
- 可按唯一 Order ID 载入已有且尚未 `all_confirmed` 的 Order，并继续搜索新 SKU、补充设计图。
- “当前 Order 继续添加 SKU”用于当前批次成功后的连续操作；“载入已有 Order 并搜索 SKU”用于跨时间恢复历史 Order。
- Seller 账号与密码输入框使用相同宽度；从已保存账号下拉列表切换时自动登录。
- Order 设计清单增加独立缩略图列，点击小图时才按需读取网站原图并打开预览。
- 已有 Order 行增加同步的 Product SKU 输入框，两个 SKU 输入框内容始终一致。
- “当前 Order 继续添加 SKU”移动到新建 Order 按钮右侧，批量图片操作按钮和默认设置合并为一行。
- 订单确认的“读取订单列表”默认仅处理最新前 20 个 Order，并只为这 20 个读取缩略图；订单列表页面的读取等待时间独立设为最多 120 秒，以适应历史订单较多的 seller。
- 对订单量特别大的 seller，可直接输入唯一的 Order ID 并读取该 Order 的设计清单，完全跳过超长订单列表；确认后会直接核查该 Order 是否仍存在待确认设计。

当前批次中的图片共用同一个 SKU、Definition 和 Product Type，但每张图片可以使用不同的 Type Option、Quantity 和 Code 后缀。

## 安装与运行

建议使用 Python 3.11：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python run.py
```

复制 `.env.example` 为 `.env`，填写测试账号：

```dotenv
HIPERSONALIZATION_BASE_URL=https://hipersonalization.com
HIPERSONALIZATION_SELLER_USERNAME=
HIPERSONALIZATION_SELLER_PASSWORD=
```

`.env` 已加入 `.gitignore`，不得提交真实凭据。正式交付给 seller 时，建议由用户在登录窗口输入密码，不在安装包中包含 `.env`。

## 使用流程

1. 首次使用时填写 Seller 账号和密码，点击“登录并验证权限”。登录成功后账号会进入下拉列表，密码由系统凭据库保存。
2. 后续启动会自动登录上次使用的账号；需要切换时从下拉列表选择另一个账号再登录。
3. 填写 Order Title 和 Product SKU，点击“创建 Order 并搜索 SKU”。
4. 选择 Product 并读取 Definitions；程序会在 Definition 确定后自动读取 Product Types。选择 Product Type 后，点击“读取 Type Options”。
5. 点击“选择多张图片”。通过独立缩略图列确认内容，并在每一行独立设置生产位置、Type Option、Quantity 和可选的 Code 后缀（支持英文、数字、空格及 `_ - = +`）。
6. 如果所有图片使用相同设置，在批量区域选择 Type Option 和 Quantity，然后点击“应用到全部图片”。
7. 检查每一行后点击“确认并批量提交”。
8. 当前 SKU 全部成功后，修改 Product SKU 并点击“当前 Order 继续添加 SKU”，即可复用当前窗口的 Order ID。
9. 如需创建全新的 Order，点击“开始新 Order”，然后重新填写 Order Title 和 Product SKU。
10. 如需给历史未确认 Order 补图，在“已有 Order ID”填写唯一数字 ID、在上方填写新 Product SKU，然后点击“载入已有 Order 并搜索 SKU”。工具会验证订单属于当前 seller、恢复原 Order Title，并且不会创建新 Order。

订单确认流程：

1. 切换到“订单确认”分页，点击“读取订单列表”，可按 Order ID、Title 或 Status 筛选。
2. 选择目标 Order，点击“读取该 Order 产品”，检查设计清单和待确认数量。
3. 首次确认时选择 Shipping Stamp PDF 和 Stamp Type；Gift Message PDF 为可选。
4. 点击“确认并批量处理该 Order”并再次确认，工具会将资料提交到第一张设计，再依次直接确认其余设计。
5. 工具最后重新读取订单状态；只有显示 `all_confirmed` 才表示整个 Order 确认完成。
6. 如果中途失败，重新读取该 Order 后再次执行；已有 `image_confirmed` 设计会被跳过，Shipping Stamp 不会重复上传。

Code 生成规则：

- 普通图片，无后缀：`robin test2026`
- 普通图片，后缀 `A001`：`robin test2026_A001`
- 背面图片，无后缀：`BACK_robin test2026`
- 背面图片，后缀 `A001`：`BACK_robin test2026_A001`

Order Title 在创建前会自动去除首尾空格。Code 后缀支持英文、数字、空格及半角 `_ - = +`。

工具会写入线上订单。创建订单和最终批量提交前请确认 seller、标题、SKU 与图片是否正确。

## 测试

```powershell
python -m pytest -q
python -m compileall -q src run.py
```

单元测试不会连接线上网站，也不会创建订单。

## Windows 打包

```powershell
python -m pip install pyinstaller
python -m PyInstaller hipersonalization_assistant.spec --clean --noconfirm
```

输出文件位于 `dist/hipersonalization订单处理助手 v0.13 by Robin+Codex.exe`。不要把 `.env`、测试账号或本地历史数据库加入安装包。

Seller 用户可以直接复制这一份 EXE 到自己的 Windows 电脑运行，不需要同时发送 `.env`、源代码或图标文件。首次运行时由用户在软件内输入自己的账号和密码。

## macOS 测试版打包

在 Mac 终端进入本项目目录后执行：

```bash
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh
```

打包结果位于 `dist/hipersonalization订单处理助手 v0.13 by Robin+Codex.app`。这是未签名测试版；首次启动如被 macOS 拦截，请在 Finder 中右键该应用并选择“打开”，再确认一次即可。不要将 `.env`、本地账号资料或订单历史随应用发送。

本地账号数据不会写入 EXE 所在目录：

- 账号名称列表、上次登录账号和提交历史位于 `%LOCALAPPDATA%\HiPersonalizationAssistant`。
- Seller 密码由 Windows Credential Manager 保存，凭据服务名称为 `HiPersonalizationAssistant`。
- 不要把开发用 `.env` 发送给 seller；打包程序不会包含 `.env`，正式 EXE 也不会读取同目录下的 `.env`。

## 网站表单映射

工具当前根据线上页面使用以下 Gravity Forms：

- `gform_40`：创建订单，`input_2` 为 Order Title。
- `gform_42`：搜索产品，`input_3` 为 Product SKU。
- `gform_45`：选择 Product Type，`input_2` 为 Type。
- `gform_46`：创建订单产品，`input_2` 为 code、`input_3` 为 Type Option、`input_4` 为 Quantity、`input_9` 为 first image。
- `gform_47`：确认设计，`input_1` 为确认状态、`input_4` 为 Shipping Stamp PDF、`input_5` 为 Stamp Type、`input_6` 为可选 Gift Message PDF。

如果 PHP/WordPress 页面修改了表单 ID、字段名或页面 URL，需要同步更新 `client.py` 和相应测试。
