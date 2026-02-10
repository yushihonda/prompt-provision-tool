"""
Redis Stream操作サービス
"""
import json
import time
import logging
import asyncio
import redis
from typing import AsyncGenerator, Optional
from app.config import settings

logger = logging.getLogger(__name__)

# Redis接続プール
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Redisクライアントを取得（シングルトン）"""
    global _redis_client
    if _redis_client is None:
        try:
            # CELERY_BROKER_URLから接続情報を取得
            broker_url = settings.CELERY_BROKER_URL
            _redis_client = redis.from_url(broker_url, decode_responses=True)
            # 接続テスト
            _redis_client.ping()
            logger.info("Redis client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Redis client: {str(e)}")
            raise
    return _redis_client


def publish_chunk(execution_id: int, chunk: str):
    """
    チャンクをRedis Streamに送信

    Args:
        execution_id: 実行ID
        chunk: チャンクテキスト
    """
    try:
        client = get_redis_client()
        stream_name = f"execution:{execution_id}"

        # チャンクを送信（プロンプト本文は送信しない）
        msg_id = client.xadd(
            stream_name,
            {
                "type": "chunk",
                "data": json.dumps({"text": chunk}),
                "timestamp": str(int(time.time()))
            },
            maxlen=settings.REDIS_STREAM_MAX_LENGTH
        )

        # TTL設定（2時間）
        client.expire(stream_name, settings.REDIS_STREAM_TTL)

        logger.info(f"Published chunk for execution {execution_id}: {len(chunk)} chars, msg_id: {msg_id}")
    except Exception as e:
        logger.error(f"Failed to publish chunk for execution {execution_id}: {str(e)}")
        raise


def publish_complete(execution_id: int, result: dict):
    """
    完了イベントをRedis Streamに送信

    Args:
        execution_id: 実行ID
        result: 実行結果（model_used, tokens_used, execution_time等）
    """
    try:
        client = get_redis_client()
        stream_name = f"execution:{execution_id}"

        msg_id = client.xadd(
            stream_name,
            {
                "type": "complete",
                "data": json.dumps(result),
                "timestamp": str(int(time.time()))
            },
            maxlen=settings.REDIS_STREAM_MAX_LENGTH
        )

        # TTL設定（1時間）- 完了後は1時間後に削除
        client.expire(stream_name, 3600)

        logger.info(f"Published complete event for execution {execution_id}: {result}, msg_id: {msg_id}")
    except Exception as e:
        logger.error(f"Failed to publish complete for execution {execution_id}: {str(e)}")
        raise


def publish_error(execution_id: int, error_message: str):
    """
    エラーイベントをRedis Streamに送信

    Args:
        execution_id: 実行ID
        error_message: エラーメッセージ
    """
    try:
        client = get_redis_client()
        stream_name = f"execution:{execution_id}"

        client.xadd(
            stream_name,
            {
                "type": "error",
                "data": json.dumps({"message": error_message}),
                "timestamp": str(int(time.time()))
            },
            maxlen=settings.REDIS_STREAM_MAX_LENGTH
        )

        # TTL設定（1時間）- エラー後は1時間後に削除
        client.expire(stream_name, 3600)
    except Exception as e:
        logger.error(f"Failed to publish error for execution {execution_id}: {str(e)}")
        raise


def publish_cancel(execution_id: int):
    """
    キャンセルイベントをRedis Streamに送信

    Args:
        execution_id: 実行ID
    """
    try:
        client = get_redis_client()
        stream_name = f"execution:{execution_id}"

        client.xadd(
            stream_name,
            {
                "type": "cancel",
                "data": json.dumps({"message": "実行がキャンセルされました"}),
                "timestamp": str(int(time.time()))
            },
            maxlen=settings.REDIS_STREAM_MAX_LENGTH
        )

        # TTL設定（1時間）- キャンセル後は1時間後に削除
        client.expire(stream_name, 3600)
    except Exception as e:
        logger.error(f"Failed to publish cancel for execution {execution_id}: {str(e)}")
        raise


def publish_workflow_next_step(execution_id: int, next_step_data: dict):
    """
    ワークフロー次のステップイベントをRedis Streamに送信

    Args:
        execution_id: 現在の実行ID
        next_step_data: 次のステップ情報（next_execution_id, next_step_order, step_name, workflow_name等）
    """
    try:
        client = get_redis_client()
        stream_name = f"execution:{execution_id}"

        msg_id = client.xadd(
            stream_name,
            {
                "type": "workflow_next_step",
                "data": json.dumps(next_step_data),
                "timestamp": str(int(time.time()))
            },
            maxlen=settings.REDIS_STREAM_MAX_LENGTH
        )

        # TTL設定（2時間）
        client.expire(stream_name, settings.REDIS_STREAM_TTL)

        logger.info(f"Published workflow_next_step for execution {execution_id}: {next_step_data}, msg_id: {msg_id}")
    except Exception as e:
        logger.error(f"Failed to publish workflow_next_step for execution {execution_id}: {str(e)}")
        raise


def is_cancelled(execution_id: int) -> bool:
    """
    実行がキャンセルされているかチェック

    Args:
        execution_id: 実行ID

    Returns:
        キャンセルされている場合True
    """
    try:
        from app.database import SessionLocal
        from app.models import Execution

        db = SessionLocal()
        try:
            execution = db.query(Execution).filter(Execution.id == execution_id).first()
            if execution:
                return execution.status == "cancelled"
            return False
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to check cancellation status for execution {execution_id}: {str(e)}")
        return False


async def subscribe_stream(execution_id: int) -> AsyncGenerator[dict, None]:
    """
    Redis Streamを購読（SSE用）

    Args:
        execution_id: 実行ID

    Yields:
        ストリームイベント（type, data, timestamp）
    """
    client = get_redis_client()
    stream_name = f"execution:{execution_id}"
    last_id = "0"  # 最初から

    try:
        logger.info(f"Subscribing to stream {stream_name} from {last_id}")

        # 最初に既存のメッセージを非ブロッキングで取得
        logger.info(f"Fetching existing messages from {stream_name} with last_id={last_id}")
        try:
            existing_messages = await asyncio.to_thread(
                client.xread,
                {stream_name: last_id},
                count=100,  # 既存メッセージを多く取得
                block=0  # 非ブロッキング
            )
            logger.info(f"xread returned for {stream_name}: {type(existing_messages)}, is_empty: {not existing_messages}, length: {len(existing_messages) if existing_messages else 0}")
        except Exception as e:
            logger.error(f"Error fetching existing messages from {stream_name}: {str(e)}", exc_info=True)
            existing_messages = []

        if existing_messages and len(existing_messages) > 0:
            logger.info(f"Found {len(existing_messages)} existing streams in {stream_name}")
            for stream, msgs in existing_messages:
                for msg_id, fields in msgs:
                    def safe_decode(value, default=""):
                        if value is None:
                            return default
                        if isinstance(value, str):
                            return value
                        if isinstance(value, bytes):
                            return value.decode('utf-8')
                        return str(value)

                    event_data = {
                        "type": safe_decode(fields.get("type"), "chunk"),
                        "data": safe_decode(fields.get("data"), ""),
                        "timestamp": safe_decode(fields.get("timestamp"), str(int(time.time())))
                    }
                    logger.info(f"Yielding existing event from {stream_name}: type={event_data['type']}, data_length={len(event_data['data'])}")
                    yield event_data
                    last_id = safe_decode(msg_id, "0")

                    # 完了イベントの場合はループを抜ける
                    if event_data["type"] in ["complete", "error", "cancel"]:
                        logger.info(f"Stream {stream_name} ended with {event_data['type']} event")
                        return
        else:
            logger.info(f"No existing messages in {stream_name}, waiting for new messages")

        # その後、新しいメッセージをブロッキングで待つ
        while True:
            # ストリームから読み取り（1秒ブロック）
            # asyncio.to_thread を使用してブロッキングI/Oを非同期に実行
            messages = await asyncio.to_thread(
                client.xread,
                {stream_name: last_id},
                count=10,
                block=1000
            )

            logger.info(f"xread returned for {stream_name}: {len(messages) if messages else 0} streams")

            if not messages:
                # タイムアウト時は空のyieldで継続
                await asyncio.sleep(0.1)
                continue

            for stream, msgs in messages:
                for msg_id, fields in msgs:
                    # フィールドを辞書として返す
                    # decode_responses=Trueの場合、fieldsは既に文字列
                    # ただし、xreadの結果は常にバイト列で返される可能性があるため、安全にデコード
                    def safe_decode(value, default=""):
                        if value is None:
                            return default
                        if isinstance(value, str):
                            return value
                        if isinstance(value, bytes):
                            return value.decode('utf-8')
                        return str(value)

                    event_data = {
                        "type": safe_decode(fields.get("type"), "chunk"),
                        "data": safe_decode(fields.get("data"), ""),
                        "timestamp": safe_decode(fields.get("timestamp"), str(int(time.time())))
                    }
                    logger.info(f"Yielding event from {stream_name}: type={event_data['type']}, data_length={len(event_data['data'])}")
                    yield event_data
                    last_id = safe_decode(msg_id, "0")

                    # 完了イベントの場合はループを抜ける
                    if event_data["type"] in ["complete", "error", "cancel"]:
                        return
    except redis.exceptions.ConnectionError as e:
        logger.error(f"Redis connection error while subscribing to {stream_name}: {e}")
        # 接続エラーの場合はエラーイベントを送信して終了
        yield {
            "type": "error",
            "data": json.dumps({"message": f"Redis接続エラー: {str(e)}"}),
            "timestamp": str(int(time.time()))
        }
    except Exception as e:
        logger.error(f"Error subscribing to stream for execution {execution_id}: {str(e)}")
        # エラーイベントを送信して終了
        yield {
            "type": "error",
            "data": json.dumps({"message": f"ストリーム購読エラー: {str(e)}"}),
            "timestamp": str(int(time.time()))
        }


# asyncioのインポート（subscribe_streamで使用）
import asyncio

