# jmadantic

気象庁防災情報XMLの型付きパーサーと、PULL型フィードのクライアントです。

## フィードの処理と ack

`poll()` が返すのは未処理エントリーです。電文の取得・解析・利用側の処理が成功した後に
`ack()` を呼びます。`fetch()` 自体は ack しません。

```python
from jmadantic import parse
from jmadantic.feed import FeedClient, FeedKind

client = FeedClient(FeedKind.EXTRA, user_agent="my-signage/1.0")
for entry in client.poll():
    report = parse(client.fetch(entry))
    print(report.head.title)  # 利用側の処理
    client.ack(entry)
```

取得や処理に失敗して ack しなかったエントリーは、次の `poll()` でも返ります。
フィードの応答が304でも、フィードから電文が消えていても同様です。
興味のない電文も `client.ack(entry)` または `client.ack(entry.id)` で処理済みにできます。

未処理エントリーは発見順に最大1,000件保持し、超過時は古いものを警告ログ付きで破棄します。
未処理の記録はメモリー内だけです。再起動時の取りこぼしは長期フィード（`long=True`）で補います。
既定の最小ポーリング間隔は高頻度60秒、長期3600秒です。

User-Agentの既定値は `jmadantic/<version>` です。`user_agent` で運用者の連絡先などを含む値に
上書きできます。空文字は指定できません。リポジトリURLは含めません。

開発計画と検証記録は `implementation-plan.md` と `IMPLEMENTATION_STATUS.md` を参照してください。
