# IL method body 全量校验

## 样本与映射

输入是 `app_unity3d.bin`，UnityWebData 条目表共 25 项。
`Assembly-CSharp.dll` 的条目偏移是 `1,474,648`，长度 `4,584,448`，
SHA-256 为：

```text
b27be6995d07248f860e2c0700b50d52e936b17922b5568fa24f5d6659e6334e
```

偏移口径：

```text
DLL 内文件偏移 = RVA + 1,466,968
容器内绝对偏移 = DLL 内文件偏移 + 1,474,648
```

校验：元数据 RVA `0x23439C` 映射到容器偏移 `0x39A7D4`
（`BSJB`），与容器原始字节一致。

## 结果

`tools/verify_il_bodies.py` 使用 `dncil` 严格解码；未知 opcode、截断操作数、
指令流未精确落在 `code+size`、非法终止形式都会作为失败返回，不会跳过 1 字节。

| 指标 | 结果 |
|---|---:|
| `MethodDef` | 26,688 |
| 有 IL body | 25,174 |
| 无 body（abstract / PInvoke 等） | 1,514 |
| 成功解码 body | 25,174 |
| 指令数 | 677,346 |
| 硬失败 | 0 |

复现：

```bash
python tools/verify_il_bodies.py app_unity3d.bin \
  --entry Assembly-CSharp.dll --json
```

## 终止指令例外

二进制作中有 3 个编译器生成的无限循环方法，最后一条指令是向已解码范围回跳的
`br`，而不是 `ret` / `throw` / `leave` / `endfinally`：

| 方法 | body 偏移 | 最后指令 |
|---|---:|---|
| `MiniJSON2.Json/Parser::ParseObject` | `0x16C268` | `0x16C2EF br` |
| `Script.Lexer::yylex` | `0x1B9F40` | `0x1BA695 br` |
| `Script.Parser::yyparse` | `0x1BB18C` | `0x1BC40B br` |

这 3 条没有 fall-through，代码流仍不会越过 `code_end`。默认报告把它们单列为
`non_returning_br=3`；`--strict-terminators` 可强制按原始终止指令白名单返回
这 3 条失败。

