# PC 客户端 IL 静态分析链

本目录新增的分析产物直接来自 `app_unity3d.bin -> Assembly-CSharp.dll`，
不依赖 E 盘旧反编译目录，也不使用“遇到未知 opcode 就跳 1 字节”的旧扫描器。

## 前置

```bash
python -m pip install -r requirements-analysis.txt
```

`dnfile` / `dncil` 只用于维护静态分析产物，不是 Stub 服务运行依赖。

## 统一偏移

```text
DLL 内文件偏移 = RVA + 1,466,968
容器内绝对偏移 = DLL 内文件偏移 + 1,474,648
```

本目录 TSV 的 `file_offset`、`evidence`、`read_evidence` 均为容器内绝对偏移。

## 产物

| 文件 | 内容 |
|---|---|
| [`il-body-verification.md`](il-body-verification.md) | 25,174 个 method body 的严格解码结果 |
| `key_types.tsv` | `ldstr + get_Item + unbox.any/castclass` 键类型，并补全独立 `unbox.any` token；1,076 行 / 908 键 |
| `http_method.tsv` | `httpCall` 参数对象是否为空决定的 GET/POST；433 个 callsite / 402 端点 |
| `api_callback_fanout.tsv` | API → WebApiClient 方法 → responder → `callCallbacks` 扇出 |
| `callback_subscribers.tsv` | `regist` 调用点枚举出的订阅者及其读取键、守卫和类型 |
| `il_unguarded_reads.tsv` | IL 级无守卫读键全量清单；2,595 个读取点 / 1,358 个方法 |
| [`unguarded-reads.md`](unguarded-reads.md) | 上述无守卫读取点的可读版本 |
| `response_shapes.tsv` | 402 个端点的 envelope / bare-map 判决与 IL 偏移 |

## 重跑

```bash
python tools/verify_il_bodies.py app_unity3d.bin

python tools/extract_key_types.py app_unity3d.bin \
  --out docs/analysis/key_types.tsv

python tools/classify_http_methods.py app_unity3d.bin \
  --out docs/analysis/http_method.tsv

python tools/analyze_callbacks.py app_unity3d.bin \
  --out docs/analysis/api_callback_fanout.tsv \
  --subscribers-out docs/analysis/callback_subscribers.tsv

python tools/il_unguarded_reads.py app_unity3d.bin \
  --out-tsv docs/analysis/il_unguarded_reads.tsv \
  --out-md docs/analysis/unguarded-reads.md

python tools/extract_response_shapes.py app_unity3d.bin \
  --out docs/analysis/response_shapes.tsv

python tools/verify_response_shape_evidence.py \
  --assembly app_unity3d.bin
```

## 关键结论

- 402 个端点中只有 `common/getRevisions` 静态确认以 GET 发出；其余 432 个
  callsite 的参数对象非空，走 `WWWForm` POST。
- `common/periodicInquiry` 的回包会经 `PeriodicRounder.callCallbacks`
  分发给 4 个订阅者。`ChatInfo::setOperationMessage` 对 `gmMessage` 的读取
  没有 `ContainsKey` 守卫。
- `politicPoint` 与 `nextTriggerPoliticPoint` 的读取类型是 `System.Double`；
  大写 `PoliticPoint` 另有一处 `System.Int32`，两者不能混用。
- 响应形状矩阵为 21 个 bare-map 覆盖端点、381 个 envelope 端点；
  `response_shapes.tsv` 为每条端点保留证据偏移。

