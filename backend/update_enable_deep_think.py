#!/usr/bin/env python3
"""
既存のプロンプトに対してenable_deep_thinkを更新するスクリプト

使用方法:
    python update_enable_deep_think.py
"""

import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import Prompt

def update_enable_deep_think():
    """既存のプロンプトに対してenable_deep_thinkを更新"""
    db = SessionLocal()
    try:
        # すべてのプロンプトを取得
        prompts = db.query(Prompt).all()
        
        print(f"プロンプト総数: {len(prompts)}")
        
        updated_count = 0
        for prompt in prompts:
            # enable_deep_thinkがNoneまたは存在しない場合
            enable_deep_think = getattr(prompt, 'enable_deep_think', None)
            
            if enable_deep_think is None:
                # Gemini 2.5/3系のモデルの場合はTrue、それ以外はFalse
                if prompt.model_type and (
                    prompt.model_type.startswith('gemini-2.5') or 
                    prompt.model_type.startswith('gemini-3') or
                    prompt.model_type == 'gemini-3-pro-preview'
                ):
                    prompt.enable_deep_think = True
                    print(f"  Prompt {prompt.id} ({prompt.name}): enable_deep_think = True (Gemini 2.5/3系)")
                    updated_count += 1
                else:
                    prompt.enable_deep_think = False
                    print(f"  Prompt {prompt.id} ({prompt.name}): enable_deep_think = False (非Gemini 2.5/3系)")
                    updated_count += 1
            else:
                print(f"  Prompt {prompt.id} ({prompt.name}): enable_deep_think = {enable_deep_think} (既に設定済み)")
        
        if updated_count > 0:
            db.commit()
            print(f"\n✅ {updated_count}件のプロンプトを更新しました")
        else:
            print("\n✅ 更新が必要なプロンプトはありませんでした")
            
    except Exception as e:
        db.rollback()
        print(f"\n❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("enable_deep_think 更新スクリプト")
    print("=" * 60)
    print()
    update_enable_deep_think()
    print()
    print("=" * 60)
    print("完了")
    print("=" * 60)

