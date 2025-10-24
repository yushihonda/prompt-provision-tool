# ローカル開発環境セットアップガイド

## 📋 前提条件

- Python 3.11 以上
- MySQL 8.0 以上
- Git

---

## 🚀 セットアップ手順

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd prompt-provision-tool
```

### 2. Python仮想環境の作成

```bash
# 仮想環境を作成
python3 -m venv venv

# 仮想環境を有効化
source venv/bin/activate  # Mac/Linux
# または
venv\Scripts\activate  # Windows
```

### 3. 依存パッケージのインストール

```bash
pip install --upgrade pip
pip install -r backend/requirements.txt
```

### 4. MySQLデータベースの準備

```bash
# MySQLにログイン
mysql -u root -p

# データベースとユーザーを作成
CREATE DATABASE prompt_provision_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'prompt_tool_user'@'localhost' IDENTIFIED BY 'local_dev_password';
GRANT ALL PRIVILEGES ON prompt_provision_db.* TO 'prompt_tool_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 5. 環境変数の設定

```bash
# ローカル開発用の.envファイルをコピー
cd backend
cp .env.local .env

# .envファイルを編集してAPIキーを設定
nano .env
```

**必ず設定する項目：**
```env
OPENAI_API_KEY=sk-proj-your-api-key-here
GEMINI_API_KEY=your-gemini-api-key-here
```

### 6. データベースマイグレーション

```bash
cd backend
alembic upgrade head
```

### 7. 初期管理者アカウントの作成

```bash
# bcryptのバージョン問題がある場合
pip install 'bcrypt==4.0.1'

# 管理者アカウント作成
python -m app.init_admin

# または直接Pythonスクリプトで
python3 << 'EOF'
from app.auth import get_password_hash
from app.database import SessionLocal
from app.models import Account, AccountType

db = SessionLocal()
try:
    hashed = get_password_hash('admin123')
    admin = Account(
        username='admin',
        email='admin@localhost',
        hashed_password=hashed,
        account_type=AccountType.PARENT,
        is_active=True
    )
    db.add(admin)
    db.commit()
    print('✓ 管理者アカウントを作成しました')
except Exception as e:
    print(f'エラー: {e}')
    db.rollback()
finally:
    db.close()
EOF
```

### 8. アプリケーションの起動

```bash
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 🌐 アクセス

起動後、以下のURLでアクセスできます：

- **API ドキュメント**: http://127.0.0.1:8000/docs
- **トップページ**: http://127.0.0.1:8000/
- **管理者ログイン**: http://127.0.0.1:8000/static/admin/login.html
- **ユーザーログイン**: http://127.0.0.1:8000/static/user/login.html

**デフォルトログイン情報：**
- ユーザー名: `admin`
- パスワード: `admin123`

---

## 🔧 開発時のコマンド

### データベースのリセット

```bash
cd backend
alembic downgrade base
alembic upgrade head
python -m app.init_admin
```

### 新しいマイグレーションの作成

```bash
cd backend
alembic revision --autogenerate -m "説明"
alembic upgrade head
```

### テスト実行

```bash
cd backend
pytest
```

---

## 📁 ディレクトリ構造

```
prompt-provision-tool/
├── backend/
│   ├── .env                  # 環境変数（Gitに含めない）
│   ├── .env.local           # ローカル開発用サンプル
│   ├── alembic/             # DBマイグレーション
│   ├── app/
│   │   ├── main.py         # FastAPIアプリケーション
│   │   ├── models.py       # データベースモデル
│   │   ├── schemas.py      # Pydanticスキーマ
│   │   ├── auth.py         # 認証関連
│   │   ├── api/            # APIエンドポイント
│   │   └── services/       # 外部サービス連携
│   └── requirements.txt    # Python依存パッケージ
├── frontend/               # HTML/CSS/JS
│   ├── admin/             # 管理画面
│   ├── user/              # ユーザー画面
│   └── css/               # スタイルシート
└── deployment/            # デプロイ用設定
```

---

## 🔍 トラブルシューティング

### bcryptエラー

```bash
pip uninstall bcrypt
pip install 'bcrypt==4.0.1'
```

### MySQLに接続できない

```bash
# MySQLが起動しているか確認
sudo systemctl status mysql  # Linux
brew services list | grep mysql  # Mac
```

### ポート8000が使用中

```bash
# 別のポートを使用
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

---

## 🚢 本番環境へのデプロイ

ローカルで開発した変更を本番環境に反映：

```bash
# 変更したファイルをサーバーにアップロード
rsync -av backend/app/ conoha:/opt/prompt-provision-tool/backend/app/

# サービスを再起動
ssh conoha "sudo systemctl restart prompt-tool"
```

---

## 📝 開発のベストプラクティス

1. **`.env`ファイルは絶対にGitにコミットしない**
2. **本番環境の設定は`.env`、ローカル開発は`.env.local`を使用**
3. **データベースの変更は必ずマイグレーションを作成**
4. **コード変更後は必ずテストを実行**
5. **本番環境へのデプロイ前にローカルで動作確認**

---

Happy Coding! 🎉

