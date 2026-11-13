# 0.1.0の公開手順（人間が実施）

この文書は手順だけです。公開用ワークフローの追加、Trusted Publisherの登録、
TestPyPI・PyPIへのアップロードはまだ行っていません。

## 公開前の確認

1. PyPIでのプロジェクト名の利用可否、作者・ライセンス・URL等の配布メタデータを確認する。
   気象庁コンテンツの利用規約は、ライブラリ自体のコードのライセンスを定めるものではない。
2. `pyproject.toml` と `pyjmaxml/_version.py` がともに `0.1.0` であること、
   READMEの出典表示とCHANGELOGを確認する。
3. READMEの開発コマンドでテスト・型検査を行う。Python 3.11・3.12・3.13のCI結果も確認する。
   テスト・CIから気象庁へアクセスしない。`tests/golden/` を変更しない。
4. 配布物を作る。uvの[公式手順](https://docs.astral.sh/uv/guides/package/)を参照。

```sh
uv build --no-sources
python -m venv .release-check
# Windowsでは以下のPythonを .release-check/Scripts/python.exe に置き換える
.release-check/bin/python -m pip install dist/pyjmaxml-0.1.0-py3-none-any.whl
.release-check/bin/python examples/poll_warnings.py --offline-sample tests/data/samples/15_16_03_241226_VPWW55.xml --city 0121400
```

wheelに生成クラス・コード表・`py.typed` があること、sdistにREADME・CHANGELOG・
この手順・examplesがあることを確認する。出力が過去サンプルであることと、出典・加工主体の表示も確認する。
配布物のSHA-256を記録し、以降は検証した同じファイルを使う。

## TestPyPI

1. 人間がTestPyPIへログインし、Trusted Publisherを設定する。新規プロジェクトでは
   [Pending Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)を使える。
   登録だけでは名前は予約されない。実際のGitHub所有者・リポジトリ・公開ワークフロー名・Environmentを指定する。
2. その設定に一致する公開ワークフローを別途レビューして追加する。
   公開ジョブには `permissions: id-token: write` を設定し、承認を必要とするEnvironmentを使う。
   検証済みの配布物を `pypa/gh-action-pypi-publish@release/v1` に渡し、
   `repository-url: https://test.pypi.org/legacy/` を指定する。
   [Trusted Publishingの公式手順](https://docs.pypi.org/trusted-publishers/using-a-publisher/)に従う。
3. 人間がジョブの配布物と宛先を確認して実行する。
4. 新しいvenvで、依存は通常のPyPIから入れたうえでTestPyPIの本体を確認する。
   次の例の `--no-deps` は依存の取得先をTestPyPIと混在させないために使う。

```sh
python -m pip install 'xsdata>=26.10,<27' 'lxml>=5'
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps pyjmaxml==0.1.0
python examples/poll_warnings.py --offline-sample tests/data/samples/15_16_03_241226_VPWW55.xml --city 0121400
```

## PyPI

1. TestPyPIの結果を確認後、PyPI側にも別途Trusted Publisherを設定する。
2. 同じSHA-256の配布物を使い、公開ジョブの `repository-url` を省略してPyPIへ送る設定をレビューする。
3. 人間が宛先と配布物を確認して実行する。新規venvで `pip install pyjmaxml==0.1.0` と
   オフラインの使用例を確認する。
4. 実際の公開後にREADMEのインストール手順とCHANGELOGの公開日を更新する。
