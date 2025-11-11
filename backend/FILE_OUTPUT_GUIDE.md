# ファイル出力機能ガイド

プロンプト実行結果をCSV、PDF、DOCX、Markdown、TXT形式で出力する機能です。

## 機能概要

- **出力形式**: CSV、PDF、DOCX、Markdown、TXT
- **添付ファイル対応**: プロンプト実行時に複数のファイルを添付可能
- **ファイルダウンロード**: 実行結果を後からファイルとしてダウンロード可能

## API使用方法

### 1. プロンプト実行時にファイル出力を指定

```json
POST /api/execute
{
  "prompt_id": 1,
  "input_data": {
    "text": "分析したいテキスト..."
  },
  "output_format": "csv",  // csv, pdf, docx, md, txt
  "attachments": [
    {
      "filename": "data.csv",
      "content": "項目名,値\n項目1,100\n項目2,200"
    },
    {
      "filename": "notes.md",
      "content": "# メモ\n\n重要な情報..."
    }
  ]
}
```

**レスポンス例:**
```json
{
  "output": "分析結果のテキスト...",
  "model_used": "gpt-5-thinking",
  "tokens_used": 1500,
  "execution_time": 2500,
  "status": "success",
  "file_output": {
    "filename": "output_1_1234567890.csv",
    "content": "base64エンコードされたファイル内容",
    "format": "csv",
    "size": 1024
  }
}
```

### 2. 実行結果をファイルとしてダウンロード

```
GET /api/execute/download/{execution_id}?output_format=csv
```

**パラメータ:**
- `execution_id`: 実行ID（必須）
- `output_format`: 出力形式（csv, pdf, docx, md, txt、デフォルト: txt）

**レスポンス:**
- Content-Type: ファイル形式に応じたMIMEタイプ
- Content-Disposition: ファイル名を含むダウンロードヘッダー
- ファイルのバイナリデータ

## 出力形式の詳細

### CSV形式
- テキストをCSV形式に変換
- タブ区切りまたはカンマ区切りを自動検出
- Excel対応（BOM付きUTF-8）

### PDF形式
- ReportLabを使用してPDF生成
- A4サイズ、適切な余白設定
- 日本語フォント対応

### DOCX形式
- python-docxを使用してWord文書生成
- Markdown形式の見出しを自動認識
- 日本語フォント対応（游ゴシック）

### Markdown形式
- テキストをそのままMarkdown形式で出力
- 拡張子: .md

### TXT形式
- プレーンテキスト形式で出力
- 拡張子: .txt

## 添付ファイルの使用方法

### テキスト形式で添付

```json
{
  "attachments": [
    {
      "filename": "data.csv",
      "content": "項目名,値\n項目1,100"
    }
  ]
}
```

### Base64エンコード形式で添付

```json
{
  "attachments": [
    {
      "filename": "data.csv",
      "content": "5byg5LiJ5LiA5LiqLOWApA=="
    }
  ]
}
```

**注意**: Base64デコードに失敗した場合は、テキストとして扱われます。

## 使用例

### 例1: CSV形式で出力

```bash
curl -X POST "http://localhost:8000/api/execute" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_id": 1,
    "input_data": {
      "text": "データ分析結果..."
    },
    "output_format": "csv"
  }'
```

### 例2: PDF形式で出力（添付ファイル付き）

```bash
curl -X POST "http://localhost:8000/api/execute" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_id": 2,
    "input_data": {
      "data": "商品名,売上高\n商品A,1500000\n商品B,2000000"
    },
    "output_format": "pdf",
    "attachments": [
      {
        "filename": "raw_data.csv",
        "content": "商品名,売上高,販売数量\n商品A,1500000,500\n商品B,2000000,800"
      },
      {
        "filename": "notes.md",
        "content": "# 分析メモ\n\n2024年第1四半期のデータ"
      }
    ]
  }'
```

### 例3: 実行結果をダウンロード

```bash
curl -X GET "http://localhost:8000/api/execute/download/123?output_format=pdf" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -o output.pdf
```

## エラーハンドリング

- ファイル出力に失敗した場合、テキスト形式で返されます
- サポートされていない形式を指定した場合、`ValueError`が発生します
- 添付ファイルの処理に失敗した場合、警告ログが出力されますが処理は継続されます

## 注意事項

1. **PDF/DOCX生成**: `reportlab`と`python-docx`ライブラリが必要です
2. **ファイルサイズ**: 大きなファイルの場合は、Base64エンコード後のサイズに注意してください
3. **セキュリティ**: 添付ファイルの内容はプロンプトに追加されるため、機密情報には注意してください

## 依存ライブラリ

以下のライブラリが`requirements.txt`に追加されています：
- `reportlab==4.0.7` (PDF生成)
- `python-docx==1.1.0` (DOCX生成)

インストール方法:
```bash
cd backend
pip install -r requirements.txt
```

