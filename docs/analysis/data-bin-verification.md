# PC 安装包 data.bin 的完整验证

2026-11-14 对 `OniSoul_Setup_20140712.exe` 解出的 `app/data.bin` 做了完整比对：
**528,374,000 个字节都等于固定种子的伪随机数输出**。该文件可以从种子直接重建，
无需客户端、资源包或解密密钥，不应继续把它当作缺失游戏资源的加密容器。

## 样本身份

| 文件 | 长度（字节） | SHA-256 |
|---|---:|---|
| `《鬼武者魂》客户端.rar` | 653,678,340 | `cddab26ea957b34dd22e405266e1b86868658b176bc8dec044497a9ff1b0550a` |
| 安装包中的 `app/data.bin` | 528,374,000 | `c017a1eb4a01c826b8761faa0c48494ece0c64684399d51b69fc3d7893e639c6` |

安装程序长度为 653,677,906 字节，经 innoextract 1.9 静态解包；验证未运行安装程序
或游戏，也未修改输入文件。仅代码、验证结论入仓，安装包和二进制不入仓。

## 复现算法与结果

使用 .NET 的有种子 `System.Random`：

```csharp
var random = new System.Random(19142570);
for (long i = 0; i < 528374000; i++)
    output.WriteByte((byte)random.Next(0, 254));
```

`254` 是不包含的上界。全文件未出现 `0xfe` 或 `0xff`，但这一统计本身不足以证明
文件用途；决定性证据是生成流与原文件的**全量逐字节比对**和 SHA-256 一致。

| 检查 | 结果 |
|---|---|
| 已比较字节 | 528,374,000 |
| 不一致字节 | 0 |
| 重建流 SHA-256 | `c017a1eb4a01c826b8761faa0c48494ece0c64684399d51b69fc3d7893e639c6` |

种子的识别从滞后 55/34 的减法递推关系入手，随后恢复可复现的正种子
`19142570` 并验证全文件。此结论不推断原作者的代码、种子符号或添加文件的动机。
算法对照：[Microsoft .NET Framework Random 源码](https://github.com/microsoft/referencesource/blob/main/mscorlib/system/random.cs)。

## 本地复核

先从自己的安装包静态解出 `data.bin`，在仓库根目录用 PowerShell 运行：

```powershell
./tools/verify_pc_data_bin.ps1 -Path 'D:/解包目录/app/data.bin'
```

脚本以固定大小缓冲区比较数据并打印 JSON，无需 Python 包、MySQL 或全部文件驻留
内存。退出码 `0` 表示已验证指定长度、所有字节及已知哈希；`1` 表示不匹配。
`FirstMismatchOffset=-1` 表示已读取范围没有差异，**不单独代表完整文件验证通过**；
空文件或截断的正确前缀也会因长度不符返回失败。输入文件不存在或不可读时会报错退出。

## 对资源补全的意义

该结论只适用于上述指纹的 PC 包。Unity 资源仍应从安装包内的 `cache/data7/*.d`
以及确有来源的其他缓存中提取，独立音频还在 `sound/` 下；这些内容与随机填充文件
分开存放。已有缓存提取方法见 [`repro-launcher-login.md`](../repro-launcher-login.md#十从客户端缓存还原-pc-资产包方法进仓二进制不入仓)。

完整复现 `data.bin` 不代表已恢复服务端、缺失的角色包或全部游戏内容，也不能将
其他版本中同名的文件直接判为填充数据。
