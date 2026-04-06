# Redis + ストリーミング + ローカルワーカー 要件定義書

> 注: 当初は Celery ベースでしたが、ローカルワーカー実行方式に移行済みです。

## 1. 概要

### 1.1 目的
現在のFastAPI + asyncio.Taskによるバックグラウンド処理を、Celery + Redis + ストリーミング + Web Workerアーキテクチャに移行し、以下の要件を満たす：

- **長時間実行対応**: 1時間程度の実行時間に対応
- **リアルタイムストリーミング**: AI APIの応答をリアルタイムで配信
- **スケーラビリティ**: 複数ワーカーによる並列処理
- **プロンプト漏洩防止**: 既存のセキュリティ要件を維持

### 1.2 前提条件
- **実行時間**: 通常1時間程度（最大2時間を想定）
- **AI API**: OpenAI (GPT) および Google (Gemini)
- **セキュリティ**: プロンプトは必ず漏れないように（暗号化、クライアント非送信、ガードレール）

### 1.3 現状の課題
- ポーリングによるサーバー負荷
- リアルタイム性の欠如
- 長時間実行時のタイムアウト
- スケーラビリティの制約

---

## 2. アーキテクチャ設計

### 2.1 システム構成図

```
┌─────────────────────────────────────────────────────────────┐
│                        Client (Browser)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Main Thread   │  │ Web Worker   │  │ UI Updates   │     │
│  │ (UI Control)  │◄─┤ (SSE Client) │─►│ (Real-time)  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└───────────────────────────┬───────────────────────────────────┘
                            │ HTTP/SSE
                            │
┌───────────────────────────▼───────────────────────────────────┐
│                    FastAPI Server                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ API Endpoints│  │ SSE Endpoint │  │ Celery Client │     │
│  │ (REST)       │  │ (Streaming)  │  │ (Task Dispatch)│    │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└───────────────────────────┬───────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼────────┐  ┌──────▼──────┐  ┌───────▼────────┐
│     Redis       │  │   Celery    │  │     MySQL      │
│  ┌──────────┐  │  │   Worker    │  │                │
│  │  Broker  │  │  │  ┌────────┐ │  │  - Accounts   │
│  │  (Queue) │  │  │  │  Tasks  │ │  │  - Prompts    │
│  └──────────┘  │  │  │  (AI)   │ │  │  - Executions │
│  ┌──────────┐  │  │  └────────┘ │  │                │
│  │  Backend │  │  │  ┌────────┐ │  └────────────────┘
│  │ (Result) │  │  │  │Stream  │ │
│  └──────────┘  │  │  │Publisher│ │
│  ┌──────────┐  │  │  └────────┘ │
│  │  Stream  │  │  └────────────┘
│  │ (Chunks) │  │
│  └──────────┘  │
└────────────────┘
```

### 2.2 データフロー

#### 2.2.1 実行リクエストフロー
```
1. Client → POST /api/execute
2. FastAPI → Executionレコード作成 (status: pending)
3. FastAPI → Celery Task Queue (Redis) にタスク送信
4. FastAPI → execution_id を即座に返却
```

#### 2.2.2 タスク実行フロー
```
1. Celery Worker → タスク受信
2. Celery Worker → Execution status: processing に更新
3. Celery Worker → プロンプト復号化（サーバー側のみ）
4. Celery Worker → AI API呼び出し（ストリーミング）
5. Celery Worker → チャンクをRedis Streamに送信
6. Celery Worker → 完了時にExecution status: success/error に更新
```

#### 2.2.3 ストリーミング配信フロー
```
1. Client (Web Worker) → GET /api/execute/{execution_id}/stream
2. FastAPI → Redis Streamを監視
3. FastAPI → チャンクをSSE形式で配信
4. Web Worker → チャンクを受信してメインスレッドに通知
5. Main Thread → UI更新（リアルタイム表示）
```

---

## 3. 技術仕様

### 3.1 Celery設定

#### 3.1.1 基本設定
```python
# config.py
CELERY_BROKER_URL: str = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
CELERY_TASK_SERIALIZER: str = "json"
CELERY_RESULT_SERIALIZER: str = "json"
CELERY_ACCEPT_CONTENT: list = ["json"]
CELERY_TIMEZONE: str = "Asia/Tokyo"
```

#### 3.1.2 長時間実行対応設定
```python
# タスクタイムアウト設定（1時間 + バッファ）
CELERY_TASK_TIME_LIMIT: int = 3900  # 65分（ハードリミット）
CELERY_TASK_SOFT_TIME_LIMIT: int = 3600  # 60分（ソフトリミット）

# ワーカーメモリ管理
CELERY_WORKER_MAX_MEMORY_PER_CHILD: int = 500000  # 500MB
CELERY_WORKER_MAX_TASKS_PER_CHILD: int = 50  # 50タスク後に再起動

# リトライ設定
CELERY_TASK_MAX_RETRIES: int = 3
CELERY_TASK_DEFAULT_RETRY_DELAY: int = 60  # 60秒
```

### 3.2 Redis設定

#### 3.2.1 Stream構造
- **Stream名**: `execution:{execution_id}`
- **フィールド**:
  ```json
  {
    "type": "chunk" | "complete" | "error" | "cancel" | "progress",
    "data": "チャンクデータ（JSON文字列）",
    "timestamp": "Unix timestamp",
    "progress": 0.0-1.0 (オプション),
    "elapsed_time": 秒数 (オプション)
  }
  ```

#### 3.2.2 Stream保持期間
- **TTL**: 7200秒（2時間）
- **最大長**: 10000エントリ（チャンク数）
- **完了後**: 結果をDBに保存後、1時間後にStream削除

### 3.3 SSE (Server-Sent Events) 設定

#### 3.3.1 接続設定
```python
# 接続タイムアウト
SSE_CONNECTION_TIMEOUT: int = 5400  # 90分

# ハートビート間隔
SSE_HEARTBEAT_INTERVAL: int = 30  # 30秒ごとに空イベント送信

# リトライ設定
SSE_RETRY_INTERVAL: int = 3000  # 3秒（クライアント側）
```

#### 3.3.2 イベント形式
```
event: chunk
data: {"type": "chunk", "data": "テキストチャンク", "timestamp": 1234567890}

event: progress
data: {"type": "progress", "progress": 0.5, "elapsed_time": 1800}

event: complete
data: {"type": "complete", "result": {...}}

event: error
data: {"type": "error", "message": "エラーメッセージ"}
```

### 3.4 Web Worker設定

#### 3.4.1 再接続設定
```javascript
const RECONNECT_DELAY = 5000;  // 5秒
const MAX_RECONNECT_ATTEMPTS = 10;
const HEARTBEAT_TIMEOUT = 60000;  // 60秒（ハートビート未受信時のタイムアウト）
```

---

## 4. セキュリティ要件

### 4.1 プロンプト漏洩防止（既存要件の維持）

#### 4.1.1 暗号化
- **保存**: Fernet暗号化（`encrypted_content`カラム）
- **復号**: サーバー側（Celery Worker）のみ
- **送信**: クライアントにはプロンプト本文を送信しない

#### 4.1.2 ガードレール
- **OpenAI**: systemメッセージとして`GUARDRAIL_PREFIX`を追加
- **Gemini**: プロンプトの先頭に`GUARDRAIL_PREFIX`を追加
- **設定**: `ENABLE_PROMPT_GUARDRAILS=true`（デフォルト）

#### 4.1.3 出力サニタイズ
- プロンプトテンプレートと類似した出力を`[REDACTED]`でマスキング
- 類似度閾値: `SANITIZE_SIMILARITY_THRESHOLD=0.6`
- 最小マッチ長: `SANITIZE_MIN_MATCH_LEN=60`

#### 4.1.4 ログ抑止
- 完成プロンプトはログに出力しない（`LOG_FINAL_PROMPT=false`）
- 本番環境では詳細ログを抑制

### 4.2 認証・認可

#### 4.2.1 SSEエンドポイントの認証
- JWTトークン必須（`Authorization: Bearer <token>`）
- 実行権限チェック（`account_prompts`テーブルで確認）
- 実行IDとアカウントIDの一致確認

#### 4.2.2 Redis Streamのアクセス制御
- Stream名に`execution_id`を含める（推測困難）
- 認証済みユーザーのみアクセス可能

---

## 5. 実装詳細

### 5.1 ファイル構成

```
backend/
├── app/
│   ├── celery_app.py              # Celeryアプリケーション初期化
│   ├── tasks/
│   │   ├── __init__.py
│   │   └── execution_tasks.py    # 実行タスク定義
│   ├── services/
│   │   └── redis_service.py      # Redis Stream操作
│   ├── api/
│   │   └── execute.py             # SSEエンドポイント追加
│   └── config.py                  # 設定追加

frontend/
└── user/
    └── js/
        └── execution-worker.js    # Web Worker実装
```

### 5.2 Celeryタスク実装

#### 5.2.1 タスク定義
```python
# backend/app/tasks/execution_tasks.py
from app.celery_app import celery_app
from app.services.redis_service import redis_service
from app.services.openai_service import openai_service
from app.services.gemini_service import gemini_service

@celery_app.task(
    bind=True,
    time_limit=3900,  # 65分
    soft_time_limit=3600,  # 60分
    max_retries=3,
    default_retry_delay=60
)
def execute_prompt_task(
    self,
    execution_id: int,
    prompt_id: int,
    input_data: dict,
    output_format: str = "txt",
    attachments: list = None,
    enable_deep_think: bool = None
):
    """
    プロンプト実行タスク（ストリーミング対応）
    
    Args:
        execution_id: 実行ID
        prompt_id: プロンプトID
        input_data: 入力データ
        output_format: 出力形式
        attachments: 添付ファイル
        enable_deep_think: Deep Think有効化フラグ
    """
    # 1. Execution status: processing に更新
    # 2. プロンプト復号化（サーバー側のみ）
    # 3. AI API呼び出し（ストリーミング）
    # 4. チャンクをRedis Streamに送信
    # 5. 完了時にExecution status: success/error に更新
```

#### 5.2.2 ストリーミング処理
```python
# AI API呼び出し（ストリーミング）
async for chunk in ai_service.execute_streaming(...):
    # チャンクをRedis Streamに送信
    redis_service.publish_chunk(execution_id, chunk)
    
    # キャンセルチェック
    if redis_service.is_cancelled(execution_id):
        redis_service.publish_cancel(execution_id)
        return

# 完了時に結果を送信
redis_service.publish_complete(execution_id, result)
```

### 5.3 Redis Stream操作

#### 5.3.1 チャンク送信
```python
# backend/app/services/redis_service.py
def publish_chunk(execution_id: int, chunk: str):
    """チャンクをRedis Streamに送信"""
    stream_name = f"execution:{execution_id}"
    redis_client.xadd(
        stream_name,
        {
            "type": "chunk",
            "data": json.dumps({"text": chunk}),
            "timestamp": int(time.time())
        },
        maxlen=10000  # 最大10000エントリ
    )
    # TTL設定（2時間）
    redis_client.expire(stream_name, 7200)
```

#### 5.3.2 ストリーム購読
```python
async def subscribe_stream(execution_id: int):
    """Redis Streamを購読（SSE用）"""
    stream_name = f"execution:{execution_id}"
    last_id = "0"  # 最初から
    
    while True:
        # ストリームから読み取り
        messages = redis_client.xread(
            {stream_name: last_id},
            count=10,
            block=1000  # 1秒ブロック
        )
        
        for stream, msgs in messages:
            for msg_id, fields in msgs:
                yield fields
                last_id = msg_id
```

### 5.4 SSEエンドポイント

#### 5.4.1 エンドポイント実装
```python
# backend/app/api/execute.py
from fastapi.responses import StreamingResponse

@router.get("/{execution_id}/stream")
async def stream_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    実行結果をストリーミング配信（SSE）
    
    Args:
        execution_id: 実行ID
    """
    # 認証・認可チェック
    execution = db.query(Execution).filter(
        Execution.id == execution_id,
        Execution.account_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="実行が見つかりません")
    
    async def event_generator():
        """SSEイベント生成器"""
        last_heartbeat = time.time()
        
        try:
            async for event in redis_service.subscribe_stream(execution_id):
                # ハートビート送信（30秒ごと）
                if time.time() - last_heartbeat > 30:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.time()
                
                # イベント送信
                event_type = event.get("type", "chunk")
                event_data = event.get("data", "")
                
                yield f"event: {event_type}\n"
                yield f"data: {event_data}\n\n"
                
                # 完了時はループを抜ける
                if event_type in ["complete", "error", "cancel"]:
                    break
        except Exception as e:
            # エラーイベント送信
            yield f"event: error\n"
            yield f"data: {json.dumps({'message': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Nginxバッファリング無効化
        }
    )
```

### 5.5 Web Worker実装

#### 5.5.1 Workerファイル
```javascript
// frontend/user/js/execution-worker.js
class ExecutionStreamClient {
    constructor(executionId, token) {
        this.executionId = executionId;
        this.token = token;
        this.eventSource = null;
        this.reconnectDelay = 5000;
        this.maxReconnectAttempts = 10;
        this.reconnectCount = 0;
        this.lastHeartbeat = Date.now();
        this.heartbeatTimeout = 60000; // 60秒
    }
    
    connect() {
        const url = `/api/execute/${this.executionId}/stream`;
        this.eventSource = new EventSource(url, {
            headers: {
                'Authorization': `Bearer ${this.token}`
            }
        });
        
        this.eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.lastHeartbeat = Date.now();
            
            // メインスレッドに通知
            self.postMessage({
                type: data.type,
                data: data
            });
        };
        
        this.eventSource.addEventListener('chunk', (event) => {
            const data = JSON.parse(event.data);
            self.postMessage({
                type: 'chunk',
                data: data
            });
        });
        
        this.eventSource.addEventListener('complete', (event) => {
            const data = JSON.parse(event.data);
            self.postMessage({
                type: 'complete',
                data: data
            });
            this.close();
        });
        
        this.eventSource.addEventListener('error', (event) => {
            const data = JSON.parse(event.data);
            self.postMessage({
                type: 'error',
                data: data
            });
        });
        
        this.eventSource.onerror = () => {
            // 再接続
            if (this.reconnectCount < this.maxReconnectAttempts) {
                setTimeout(() => {
                    this.reconnectCount++;
                    this.connect();
                }, this.reconnectDelay);
            } else {
                self.postMessage({
                    type: 'error',
                    data: { message: '接続に失敗しました' }
                });
            }
        };
        
        // ハートビート監視
        setInterval(() => {
            if (Date.now() - this.lastHeartbeat > this.heartbeatTimeout) {
                // ハートビート未受信 → 再接続
                this.eventSource.close();
                this.connect();
            }
        }, 10000); // 10秒ごとにチェック
    }
    
    close() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    }
}

// メインスレッドからのメッセージ受信
self.onmessage = function(e) {
    const { type, executionId, token } = e.data;
    
    if (type === 'start') {
        const client = new ExecutionStreamClient(executionId, token);
        client.connect();
        self.client = client;
    } else if (type === 'stop') {
        if (self.client) {
            self.client.close();
        }
    }
};
```

#### 5.5.2 メインスレッドでの使用
```javascript
// frontend/user/execute.html
let executionWorker = null;

function startStreaming(executionId) {
    // Web Worker起動
    executionWorker = new Worker('/static/user/js/execution-worker.js');
    
    // メッセージ受信
    executionWorker.onmessage = function(e) {
        const { type, data } = e.data;
        
        if (type === 'chunk') {
            // チャンクをUIに追加
            appendChunkToOutput(data.data.text);
        } else if (type === 'complete') {
            // 完了処理
            handleExecutionComplete(data);
        } else if (type === 'error') {
            // エラー処理
            handleExecutionError(data);
        }
    };
    
    // ストリーミング開始
    executionWorker.postMessage({
        type: 'start',
        executionId: executionId,
        token: sessionStorage.getItem('token')
    });
}

function stopStreaming() {
    if (executionWorker) {
        executionWorker.postMessage({ type: 'stop' });
        executionWorker.terminate();
        executionWorker = null;
    }
}
```

---

## 6. 移行計画

### 6.1 フェーズ1: 基盤構築（1-2週間）

#### 6.1.1 タスク
1. Celery + Redis環境構築
2. 基本的なタスク実装（非ストリーミング）
3. 既存の`asyncio.Task`をCeleryタスクに置き換え
4. テスト・動作確認

#### 6.1.2 成果物
- `backend/app/celery_app.py`
- `backend/app/tasks/execution_tasks.py`
- Celery Worker起動スクリプト
- 設定ファイル更新

### 6.2 フェーズ2: ストリーミング実装（1-2週間）

#### 6.2.1 タスク
1. Redis Stream実装
2. SSEエンドポイント実装
3. Celeryタスクでストリーミング対応
4. ハートビート実装

#### 6.2.2 成果物
- `backend/app/services/redis_service.py`
- SSEエンドポイント（`/api/execute/{execution_id}/stream`）
- ストリーミング対応タスク

### 6.3 フェーズ3: Web Worker実装（1週間）

#### 6.3.1 タスク
1. Web Worker作成
2. 自動再接続機能実装
3. フロントエンドのポーリングをWeb Workerに置き換え
4. UI更新ロジック実装

#### 6.3.2 成果物
- `frontend/user/js/execution-worker.js`
- フロントエンド更新（`execute.html`）

### 6.4 フェーズ4: テスト・最適化（1週間）

#### 6.4.1 タスク
1. 長時間実行タスクのテスト（1時間）
2. メモリ使用量の最適化
3. エラーハンドリングの強化
4. 負荷テスト

#### 6.4.2 成果物
- テストレポート
- パフォーマンスレポート
- 最適化ドキュメント

---

## 7. 非機能要件

### 7.1 パフォーマンス

#### 7.1.1 レイテンシ
- **ストリーミングレイテンシ**: < 100ms（チャンク受信からUI更新まで）
- **タスク起動時間**: < 1秒（キュー投入から実行開始まで）

#### 7.1.2 スループット
- **同時実行数**: 100タスク以上
- **チャンク送信速度**: 100チャンク/秒以上

#### 7.1.3 リソース使用量
- **メモリ**: タスクあたり < 50MB
- **CPU**: タスクあたり < 10%（平均）

### 7.2 可用性

#### 7.2.1 可用性目標
- **稼働率**: 99.9%以上
- **ダウンタイム**: 月間 < 43分

#### 7.2.2 障害対応
- **Celery Worker**: 自動再起動（systemd）
- **Redis接続**: 自動再接続（リトライ3回）
- **SSE接続**: 自動再接続（最大10回）

#### 7.2.3 リトライ
- **タスク失敗時**: 最大3回リトライ
- **リトライ間隔**: 60秒

### 7.3 セキュリティ

#### 7.3.1 認証・認可
- **SSEエンドポイント**: JWT認証必須
- **実行権限**: `account_prompts`テーブルで確認
- **Streamアクセス**: 実行IDとアカウントIDの一致確認

#### 7.3.2 データ保護
- **プロンプト**: 暗号化保存、クライアント非送信
- **ログ**: 完成プロンプトはログに出力しない
- **出力**: サニタイズ処理

### 7.4 監視・ログ

#### 7.4.1 監視項目
- **Celery Worker**: 稼働状態、タスク実行数、エラー数
- **Redis**: 接続状態、メモリ使用量、Stream数
- **タスク**: 実行時間、成功率、エラー率

#### 7.4.2 ログ出力
- **タスク開始**: INFOレベル
- **長時間実行警告**: WARNING（30分以上）
- **エラー**: ERRORレベル
- **完了**: INFOレベル

---

## 8. 依存関係

### 8.1 追加パッケージ

#### 8.1.1 Pythonパッケージ
```
celery==5.3.4
redis==5.0.1
celery[redis]==5.3.4
```

#### 8.1.2 システム要件
- **Redis**: 6.0以上
- **Python**: 3.10以上
- **Celery**: 5.3以上

### 8.2 環境変数追加

```env
# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Redis Stream
REDIS_STREAM_TTL=7200
REDIS_STREAM_MAX_LENGTH=10000

# SSE
SSE_CONNECTION_TIMEOUT=5400
SSE_HEARTBEAT_INTERVAL=30
```

---

## 9. テスト要件

### 9.1 単体テスト

#### 9.1.1 Celeryタスク
- タスク実行のテスト
- ストリーミング処理のテスト
- エラーハンドリングのテスト

#### 9.1.2 Redis Stream
- チャンク送信のテスト
- ストリーム購読のテスト
- TTL設定のテスト

#### 9.1.3 SSEエンドポイント
- イベント配信のテスト
- ハートビートのテスト
- 認証・認可のテスト

### 9.2 統合テスト

#### 9.2.1 実行フロー全体
- リクエスト → タスク実行 → ストリーミング配信 → 完了

#### 9.2.2 長時間実行
- 1時間の実行タスクのテスト
- タイムアウト時の動作確認
- 接続切断・再接続のテスト

### 9.3 負荷テスト

#### 9.3.1 同時実行
- 100タスクの同時実行
- メモリ使用量の監視
- Redis Streamの容量確認

#### 9.3.2 長時間実行
- 複数の長時間実行タスクの同時実行
- メモリリークの確認
- パフォーマンスの監視

---

## 10. デプロイ要件

### 10.1 サービス追加

#### 10.1.1 Celery Worker
```ini
# deployment/prompt-tool-celery.service
[Unit]
Description=NexMAGI Celery Worker
After=network.target redis.service

[Service]
Type=simple
User=prompt-tool
WorkingDirectory=/opt/prompt-provision-tool/backend
Environment="PATH=/opt/prompt-provision-tool/venv/bin"
ExecStart=/opt/prompt-provision-tool/venv/bin/celery -A app.celery_app worker --loglevel=info
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### 10.1.2 Redis
- 既存のRedisを使用、または新規インストール
- 永続化設定（AOF推奨）

### 10.2 起動順序

1. Redis起動
2. MySQL起動
3. Celery Worker起動
4. FastAPI起動

### 10.3 監視設定

#### 10.3.1 Celery Worker監視
- systemdのステータス監視
- ログ監視（`journalctl -u prompt-tool-celery`）

#### 10.3.2 Redis監視
- `redis-cli ping`で接続確認
- メモリ使用量の監視

---

## 11. 既存機能との互換性

### 11.1 保持する機能

- ✅ プロンプト暗号化（Fernet）
- ✅ ガードレール注入
- ✅ 出力サニタイズ
- ✅ キャンセル機能
- ✅ ファイル出力（CSV、PDF、DOCX、MD、TXT）
- ✅ 実行履歴
- ✅ アカウント統計

### 11.2 変更する機能

- 🔄 バックグラウンド処理: `asyncio.Task` → `Celery Task`
- 🔄 ステータス確認: ポーリング → SSEストリーミング
- 🔄 フロントエンド: メインスレッド → Web Worker

### 11.3 新規追加機能

- ✨ リアルタイムストリーミング
- ✨ 長時間実行対応（1時間以上）
- ✨ 自動再接続機能
- ✨ ハートビート機能

---

## 12. リスクと対策

### 12.1 技術的リスク

#### 12.1.1 Redis障害
- **リスク**: Redis停止時のタスク実行不可
- **対策**: Redisクラスタリング、自動フェイルオーバー

#### 12.1.2 Celery Worker障害
- **リスク**: Worker停止時のタスク実行不可
- **対策**: 複数Worker起動、自動再起動

#### 12.1.3 SSE接続切断
- **リスク**: 長時間実行中の接続切断
- **対策**: 自動再接続、ハートビート

### 12.2 セキュリティリスク

#### 12.2.1 プロンプト漏洩
- **リスク**: ストリーミング時のプロンプト漏洩
- **対策**: プロンプトは送信しない、チャンクのみ送信

#### 12.2.2 不正アクセス
- **リスク**: 他ユーザーの実行結果へのアクセス
- **対策**: 認証・認可チェック、実行IDとアカウントIDの一致確認

---

## 13. 参考資料

### 13.1 ドキュメント
- [Celery Documentation](https://docs.celeryq.dev/)
- [Redis Streams](https://redis.io/docs/data-types/streams/)
- [Server-Sent Events (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [Web Workers API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API)

### 13.2 既存ドキュメント
- `README.md`: システム仕様書
- `backend/app/services/openai_service.py`: OpenAI API実装
- `backend/app/services/gemini_service.py`: Gemini API実装

---

## 14. 変更履歴

| 日付 | バージョン | 変更内容 | 担当者 |
|------|-----------|---------|--------|
| 2024-XX-XX | 1.0 | 初版作成 | - |

---

**作成日**: 2024年XX月XX日  
**最終更新**: 2024年XX月XX日  
**バージョン**: 1.0

