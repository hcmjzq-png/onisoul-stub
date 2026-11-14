# PC 程序集结构复核与反编译

## 结论

本次复核推翻了旧记录中的结论“`app.unity3d` 内嵌程序集的 PE 头被裁、
Section Table 不可用，所以无法反编译”。当前提取出的
`Assembly-CSharp.dll` 是完整 PE/CLI 文件，PE 签名、3 个节区、CLI Header
和 `BSJB` 元数据根均可直接解析，`dnfile` / `dncil` 与 `ilspycmd` 也都能读取。

旧结论可能来自错误的提取偏移或不完整的中间文件，但本仓库没有保留那条路径的
逐字节提取记录，因此不推断具体是哪一步出错。旧结论不能再作为客户端程序集
不可反编译的证据。

本文只证明“当前指纹对应的 DLL 结构有效且可反编译”，不证明安装包内每个
同名中间文件都有效，也不把驼峰、双拼等源码命名的兼容写法当成 PC 版本的
权威证据。

## 两条解析路径（不可混用）

同一份程序集数据有两种读法，结论各自独立：

| 路径 | 入口 | 依赖 PE 头 | 能做什么 | 本文结论是否覆盖 |
|---|---|---|---|---|
| A. 独立 DLL | 从 bundle 里按 PE 起始切出 `Assembly-CSharp.dll`（4,584,448 B） | 是 | `ilspycmd` 工程模式反编译（2,034 个 `.cs`） | 是 |
| B. bundle 内元数据直解 | 直接定位未压缩 `app.unity3d` 内的 `BSJB` 元数据根 | 否 | 枚举类型/字段/方法、按 `ldstr` token 反查 IL | 否 |

`Assembly-CSharp` 的 `BSJB` 根在未压缩 `app.unity3d`（19,463,656 B）的文件偏移
**3,778,036**；同批还有 11 个元数据根（2236 / 10840 / 576672 / 1139100 / 1226528 /
1246888 / 1295220 / 1326076 / 1370720 / 1467584 / 6284316），与 12 个程序集名称一一对应
但当前未逐条绑定名字。

因此：路径 A 证明“提取出的 DLL 可反编译”，**不构成路径 B 的反证**，反之亦然。
早期“PE 头被裁、Section Table 不可用”的记录说的是路径 B 的取字节方式，路径 A 成立后
那条记录应当限定为“路径 B 的处理方式有误”，而不是“客户端程序集无法反编译”。
路径 B 本身仍可用，且不需要产出 DLL 就能定位到具体方法。

## 样本身份

| 文件 | 长度（字节） | SHA-256 |
|---|---:|---|
| `Assembly-CSharp.dll` | 4,584,448 | `b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e` |

12 个已提取程序集的名称、长度和 SHA-256 见
[`assembly_manifest.json`](assembly_manifest.json)。这些二进制和反编译源码
均不入仓。

## PE 结构

| 项目 | 实测值 |
|---|---|
| MZ / PE 签名 | 正常 |
| `e_lfanew` | `0x80` |
| Machine | `0x014C`（I386） |
| Section Table | 文件偏移 `376`，3 项，共 `120` 字节 |
| `.text` | RVA `0x2000`，VirtualSize `0x45EAF8`，RAW `0x200 + 0x45EC00` |
| `.rsrc` | RVA `0x462000`，VirtualSize `0x314`，RAW `0x45EE00 + 0x400` |
| `.reloc` | RVA `0x464000`，VirtualSize `0xC`，RAW `0x45F200 + 0x200` |

复核命令：

```bash
python tools/check_pc_assembly.py /path/to/Assembly-CSharp.dll --json
```

工具只读检查 MZ、PE 签名、COFF/Optional Header、Section Table、节区文件范围、
CLI Data Directory、CLI Header、Metadata RVA 和 `BSJB` 签名，并计算 SHA-256。
不执行 DLL，不依赖第三方 Python 包。

## 反编译

已用 `ilspycmd 8.2.0.7535` 完成工程模式反编译，输出 2034 个 `.cs` 文件。
仓库提供的封装会自动设置 `DOTNET_ROLL_FORWARD=Major`，并拒绝把输出写进仓库：

```powershell
python tools/decompile_pc_assembly.py `
  --ilspycmd D:/tools/ilspycmd.exe `
  --project `
  --out "$env:TEMP/onisoul-decompile-Assembly-CSharp" `
  D:/extracted/Assembly-CSharp.dll
```

默认不加 `--project` 时输出单个 C# 文件；加 `--project` 时生成 ilspy 工程和
逐类型源码。输出目录必须显式给出，且必须是仓库外的不存在目录或空目录。

`dnfile` / `dncil` 可作为独立交叉验证路径，但不写入 `requirements.txt`：
它们不是 Stub 服务运行依赖。

## 来源边界

- 本文指纹来自用户提供的 PC 客户端安装包所对应的程序集载荷；来源 bundle、未压缩长度、
  路径 B 的 `BSJB` 偏移与“提取脚本未入库”这一事实，都记在
  [`assembly_manifest.json`](assembly_manifest.json) 的 `provenance` 字段里。
- 当前仓库尚未保留“安装包 → `app.unity3d` → 独立 DLL”全过程的自动提取脚本，
  因此本文复现的是 DLL 提取完成后的结构验证和反编译步骤；这也是本文结论的复核边界。
- 安装包、主 bundle、DLL、反编译源码、IL 文本和临时输出都不提交。
- 反编译器不要放进仓库：`tools/decompile_pc_assembly.py` 优先查 `~/.cache/onisoul/tools/`，
  仓库内 `work/` 只在 `ONISOUL_ALLOW_REPO_TOOL=1` 时兜底，且 `work/` 已加入 `.gitignore`。

