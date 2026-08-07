# Telegram iOS 源代码编译指南

我们欢迎所有开发者使用我们的API和源代码在我们的平台上创建应用程序。
目前，我们对**所有开发者**有几点要求。

#补丁

1.将submodules/MtProtoKit/Sources/MTDatacenterAuthMessageService.m#51-69和submodules/MtProtoKit/Sources/MTEncryption.m#758-763 修改为你自己的RSA PUBLIC KEY
2.将submodules/TelegramCore/Sources/Network/Network.swift#530-535 修改你自己的服务器IP和服务端口
3.可以在submodules/TelegramCore/Sources/Account/Account.swift#347修改默认连接DC (默认1)
4.运行GitHub actions即可

# 创建您的Telegram应用程序

1. [**获取您自己的api_id**](https://core.telegram.org/api/obtaining_api_id) 用于您的应用程序。
2. 请**不要**为您的应用使用Telegram这个名称——或者确保您的用户了解这是非官方应用。
3. 请**不要**使用我们的标准徽标（蓝色圆圈中的白色纸飞机）作为您应用的徽标。
3. 请研究我们的[**安全指南**](https://core.telegram.org/mtproto/security_guidelines)，并妥善保护您用户的数据和隐私。
4. 请记得也发布**您的**代码，以遵守许可证要求。

# 快速编译指南

## 获取代码

```
git clone --recursive -j8 https://github.com/TelegramMessenger/Telegram-iOS.git
```

## 设置Xcode

安装Xcode（直接从 https://developer.apple.com/download/applications 或使用App Store安装）。

## 调整配置

1. 生成一个随机标识符：
```
openssl rand -hex 8
```
2. 创建一个新的Xcode项目。使用 `Telegram` 作为产品名称。使用 `org.{步骤1中的标识符}` 作为组织标识符。
3. 打开 `钥匙串访问` 并导航到 `证书`。找到 `Apple Development: your@email.address (XXXXXXXXXX)` 并双击该证书。在 `详细信息` 下，找到 `组织单位`。这就是团队ID。
4. 编辑 `build-system/template_minimal_development_configuration.json`。使用前面步骤的数据。

## 生成Xcode项目

```
python3 build-system/Make/Make.py \
    --cacheDir="$HOME/telegram-bazel-cache" \
    generateProject \
    --configurationPath=build-system/template_minimal_development_configuration.json \
    --xcodeManagedCodesigning
```

# 高级编译指南

## Xcode

1. 复制并编辑 `build-system/appstore-configuration.json`。
2. 复制 `build-system/fake-codesigning`。创建并下载配置文件，使用 `profiles` 文件夹作为权限的参考。
3. 生成Xcode项目：
```
python3 build-system/Make/Make.py \
    --cacheDir="$HOME/telegram-bazel-cache" \
    generateProject \
    --configurationPath=步骤1中的配置文件 \
    --codesigningInformationPath=步骤2中的目录
```

## IPA

1. 重复上一节的步骤。使用分发配置文件。
2. 运行：
```
python3 build-system/Make/Make.py \
    --cacheDir="$HOME/telegram-bazel-cache" \
    build \
    --configurationPath=...参见上一节... \
    --codesigningInformationPath=...参见上一节... \
    --buildNumber=100001 \
    --configuration=release_arm64
```

# 常见问题

## Xcode卡在"build-request.json not updated yet"

有时，您可能会在构建日志中看到以下消息：
```
"/Users/xxx/Library/Developer/Xcode/DerivedData/Telegram-xxx/Build/Intermediates.noindex/XCBuildData/xxx.xcbuilddata/build-request.json" not updated yet, waiting...
```

如果出现这种情况，只需取消当前构建并重新开始一个新的构建即可。

## Telegram_xcodeproj: 没有这样的包

系统重启后，自动生成的Xcode项目可能会构建失败，并伴随此错误：
```
ERROR: Skipping '@rules_xcodeproj_generated//generator/Telegram/Telegram_xcodeproj:Telegram_xcodeproj': no such package '@rules_xcodeproj_generated//generator/Telegram/Telegram_xcodeproj': BUILD file not found in directory 'generator/Telegram/Telegram_xcodeproj' of external repository @rules_xcodeproj_generated. Add a BUILD file to a directory to mark it as a package.
```

如果遇到此问题，请重新运行README中的项目生成步骤。


# 提示

## 仅模拟器构建不需要代码签名

添加 `--disableProvisioningProfiles`：
```
python3 build-system/Make/Make.py \
    --cacheDir="$HOME/telegram-bazel-cache" \
    generateProject \
    --configurationPath=配置文件路径.json \
    --codesigningInformationPath=配置文件数据路径 \
    --disableProvisioningProfiles
```

## 版本

每个版本都是使用特定的Xcode版本构建的（参见 `versions.json`）。辅助脚本会检查已安装软件的版本，如果与 `versions.json` 中指定的版本不匹配，则会报告错误。可以绕过这些检查：

```
python3 build-system/Make/Make.py --overrideXcodeVersion build ... # 不检查Xcode版本
```
