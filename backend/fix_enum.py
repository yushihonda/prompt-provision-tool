#!/usr/bin/env python3
"""
データベースのENUM型を小文字から大文字に修正するスクリプト
"""

import sys
import os

# プロジェクトルートをPythonパスに追加
sys.path.insert(0, os.path.dirname(__file__))

import pymysql
from app.config import settings

def main():
    print("🔧 データベースのENUM定義を修正します...")
    print()
    
    try:
        # データベースに接続
        conn = pymysql.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME
        )
        cursor = conn.cursor()
        
        # 現在の値を確認
        print("📋 修正前の状態:")
        cursor.execute("SHOW CREATE TABLE accounts")
        result = cursor.fetchone()
        create_statement = result[1]
        
        # account_type行を抽出
        for line in create_statement.split('\n'):
            if 'account_type' in line:
                print(f"  {line.strip()}")
        
        cursor.execute("SELECT username, account_type FROM accounts")
        accounts = cursor.fetchall()
        for username, account_type in accounts:
            print(f"  {username}: {account_type}")
        print()
        
        # ENUM定義を大文字に変更
        print("🔄 ENUM定義を変更中...")
        cursor.execute("""
            ALTER TABLE accounts 
            MODIFY COLUMN account_type ENUM('PARENT', 'CHILD') 
            COLLATE utf8mb4_unicode_ci NOT NULL
        """)
        
        # 既存のデータを大文字に更新
        print("🔄 既存データを更新中...")
        cursor.execute("UPDATE accounts SET account_type = 'PARENT' WHERE account_type IN ('parent', 'Parent')")
        parent_count = cursor.rowcount
        cursor.execute("UPDATE accounts SET account_type = 'CHILD' WHERE account_type IN ('child', 'Child')")
        child_count = cursor.rowcount
        
        conn.commit()
        
        print(f"  ✅ {parent_count} 件のPARENTアカウントを更新")
        print(f"  ✅ {child_count} 件のCHILDアカウントを更新")
        print()
        
        # 修正後の値を確認
        print("✅ 修正後の状態:")
        cursor.execute("SHOW CREATE TABLE accounts")
        result = cursor.fetchone()
        create_statement = result[1]
        
        for line in create_statement.split('\n'):
            if 'account_type' in line:
                print(f"  {line.strip()}")
        
        cursor.execute("SELECT username, account_type FROM accounts")
        accounts = cursor.fetchall()
        for username, account_type in accounts:
            print(f"  {username}: {account_type}")
        print()
        
        cursor.close()
        conn.close()
        
        print("=" * 60)
        print("🎉 修正が完了しました！")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

