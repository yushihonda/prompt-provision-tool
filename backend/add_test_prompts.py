#!/usr/bin/env python3
"""
テストプロンプトをデータベースに追加するスクリプト
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import Prompt
from app.encryption import encryption_service
import json

# テストプロンプトを読み込み
with open('test_prompts.json', 'r', encoding='utf-8') as f:
    prompts_data = json.load(f)

db = SessionLocal()

try:
    print("=" * 60)
    print("テストプロンプトをデータベースに追加")
    print("=" * 60)
    print()
    
    # created_by は管理者アカウント（ID: 1）を想定
    created_by_id = 1
    
    for i, prompt_data in enumerate(prompts_data, 1):
        print(f"{i}. {prompt_data['name']} を追加中...")
        
        # プロンプトを暗号化
        encrypted_content = encryption_service.encrypt(prompt_data['content'])
        
        # input_schemaをJSON文字列に変換
        input_schema_str = json.dumps(prompt_data['input_schema'], ensure_ascii=False)
        
        # プロンプトを作成
        db_prompt = Prompt(
            name=prompt_data['name'],
            description=prompt_data['description'],
            encrypted_content=encrypted_content,
            model_type=prompt_data['model_type'],
            input_schema=input_schema_str,
            created_by=created_by_id
        )
        
        db.add(db_prompt)
    
    db.commit()
    print()
    print("=" * 60)
    print(f"✅ {len(prompts_data)} 件のプロンプトを追加しました！")
    print("=" * 60)
    print()
    
    # 追加されたプロンプトを確認
    all_prompts = db.query(Prompt).all()
    print(f"データベース内のプロンプト総数: {len(all_prompts)}")
    print()
    print("追加されたプロンプト一覧:")
    for prompt in all_prompts:
        print(f"  - ID: {prompt.id}, 名前: {prompt.name}, モデル: {prompt.model_type}")
    
except Exception as e:
    print(f"❌ エラーが発生しました: {e}")
    db.rollback()
    import traceback
    traceback.print_exc()
finally:
    db.close()


