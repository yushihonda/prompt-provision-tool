/**
 * 実行ストリーミング用Web Worker
 * SSE接続を管理し、メインスレッドにイベントを送信
 */
class ExecutionStreamClient {
    constructor(executionId, token) {
        this.executionId = executionId;
        this.token = token;
        this.reader = null;
        this.reconnectDelay = 3000;  // 3秒（SSE_RETRY_INTERVAL）
        this.maxReconnectAttempts = 10;
        this.reconnectCount = 0;
        this.lastHeartbeat = Date.now();
        this.heartbeatTimeout = 60000;  // 60秒
        this.heartbeatCheckInterval = null;
        this.isClosed = false;
        this.isConnecting = false;  // 接続中のフラグ
    }

    connect() {
        if (this.isClosed) {
            return;
        }

        // 既に接続中の場合は処理を中断
        if (this.isConnecting) {
            return;
        }

        this.isConnecting = true;
        const url = `/api/execute/${this.executionId}/stream`;
        const client = this; // コンテキストを保持

        // EventSourceは認証ヘッダーを設定できないため、fetch APIを使用してSSE接続を確立
        // fetch APIを使用することで、Authorizationヘッダーを設定可能
        fetch(url, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${this.token}`,
                'Accept': 'text/event-stream',
                'Cache-Control': 'no-cache'
            },
            credentials: 'include'
        }).then(response => {
            // 接続が既に閉じられている場合は処理を中断
            if (client.isClosed) {
                client.isConnecting = false;
                return;
            }
            if (!response.ok) {
                // エラーレスポンスの詳細を取得
                return response.text().then(text => {
                    throw new Error(`HTTP error! status: ${response.status}, message: ${text}`);
                });
            }

            if (!response.body) {
                throw new Error('Response body is null');
            }

            // 再度チェック（非同期処理中に閉じられた可能性がある）
            if (client.isClosed) {
                client.isConnecting = false;
                return;
            }

            client.reader = response.body.getReader();
            client.isConnecting = false;  // 接続完了
            const decoder = new TextDecoder();
            let buffer = '';

            const readStream = () => {
                // 接続が閉じられている場合は処理を中断
                if (client.isClosed) {
                    return;
                }

                if (!client.reader) {
                    return;
                }

                client.reader.read().then(({ done, value }) => {
                    if (done) {
                        // ストリーム終了（正常終了の可能性もある）
                        if (!client.isClosed) {
                            self.postMessage({
                                type: 'error',
                                data: { message: 'ストリームが予期せず終了しました' }
                            });
                        }
                        return;
                    }

                    // バッファに追加
                    buffer += decoder.decode(value, { stream: true });

                    // 行ごとに処理
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || ''; // 最後の不完全な行をバッファに保持

                    let eventType = 'message';
                    let eventData = '';

                    for (const line of lines) {
                        if (line.startsWith('event:')) {
                            eventType = line.substring(6).trim();
                        } else if (line.startsWith('data:')) {
                            eventData = line.substring(5).trim();
                        } else if (line === '') {
                            // 空行でイベント完了
                            if (eventData) {
                                client.lastHeartbeat = Date.now();

                                try {
                                    const data = JSON.parse(eventData);
                                    // イベントタイプを優先（workflow_next_stepなど専用イベントタイプ）
                                    // SSEのeventTypeがworkflow_next_stepの場合はそれを優先
                                    let messageType = eventType;
                                    if (eventType === 'workflow_next_step') {
                                        // 専用イベントタイプとして処理
                                        messageType = 'workflow_next_step';
                                    } else if (eventType === 'message' || eventType === 'chunk') {
                                        // message/chunkイベントの場合はdata.typeを確認
                                        if (data.type && typeof data.type === 'string' && data.type === 'workflow_next_step') {
                                            messageType = 'workflow_next_step';
                                        } else {
                                            messageType = 'chunk';
                                        }
                                    }
                                    
                                    self.postMessage({
                                        type: messageType,
                                        data: data
                                    });
                                } catch (e) {
                                    // パースエラーの場合
                                    if (eventType === 'chunk' || eventType === 'message') {
                                        self.postMessage({
                                            type: 'chunk',
                                            data: { text: eventData }
                                        });
                                    } else {
                                        self.postMessage({
                                            type: eventType,
                                            data: { message: eventData || 'エラーが発生しました' }
                                        });
                                    }
                                }

                                // 完了イベントの場合は接続を閉じる
                                if (eventType === 'complete' || eventType === 'error' || eventType === 'cancel') {
                                    client.close();
                                    return;
                                }
                            }

                            // リセット
                            eventType = 'message';
                            eventData = '';
                        } else if (line.startsWith(':')) {
                            // コメント行（ハートビートなど）は無視
                            client.lastHeartbeat = Date.now();
                        }
                    }

                    // 続きを読み取る
                    readStream();
                }).catch(error => {
                    if (!client.isClosed) {
                        self.postMessage({
                            type: 'error',
                            data: { message: `ストリーム読み取りエラー: ${error.message}` }
                        });
                    }
                });
            };

            // readStream()を呼び出す前に再度チェック
            if (client.isClosed) {
                return;
            }

            readStream();
        }).catch(error => {
            client.isConnecting = false;  // エラー時も接続フラグをリセット
            if (client.isClosed) {
                return;
            }

            if (client.reconnectCount < client.maxReconnectAttempts) {
                setTimeout(() => {
                    if (!client.isClosed) {
                        client.reconnectCount++;
                        client.connect();
                    }
                }, client.reconnectDelay);
            } else {
                self.postMessage({
                    type: 'error',
                    data: { message: `ストリーミング接続に失敗しました（再試行回数: ${client.reconnectCount}）: ${error.message}` }
                });
            }
        });

        // ハートビート監視
        if (this.heartbeatCheckInterval) {
            clearInterval(this.heartbeatCheckInterval);
        }
        this.heartbeatCheckInterval = setInterval(() => {
            if (Date.now() - this.lastHeartbeat > this.heartbeatTimeout) {
                // ハートビート未受信 → 再接続
                if (!this.isClosed) {
                    this.close();
                    this.connect();
                }
            }
        }, 10000);  // 10秒ごとにチェック
    }

    close() {
        this.isClosed = true;
        this.isConnecting = false;  // 接続フラグもリセット

        if (this.heartbeatCheckInterval) {
            clearInterval(this.heartbeatCheckInterval);
            this.heartbeatCheckInterval = null;
        }

        // readerをキャンセル
        if (this.reader) {
            this.reader.cancel().catch(err => {
            });
            this.reader = null;
        }
    }
}

// メインスレッドからのメッセージ受信
self.onmessage = function(e) {
    const { type, executionId, token } = e.data;

    if (type === 'start') {
        // 既存のクライアントがある場合は閉じる
        if (self.client) {
            self.client.close();
            // 少し待機してから新しいクライアントを作成（非同期処理の完了を待つ）
            setTimeout(() => {
                const client = new ExecutionStreamClient(executionId, token);
                client.connect();
                self.client = client;
            }, 100);
        } else {
            const client = new ExecutionStreamClient(executionId, token);
            client.connect();
            self.client = client;
        }
    } else if (type === 'stop') {
        if (self.client) {
            self.client.close();
            self.client = null;
        }
    }
};

