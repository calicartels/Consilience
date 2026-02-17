import os
import hashlib
from datetime import datetime
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_session(team_name, password):
    response = supabase.table('sessions').select('*').eq('team_name', team_name).execute()
    
    if response.data and len(response.data) > 0:
        print(f"Error: Team name '{team_name}' already exists")
        return None
    
    password_hash = hash_password(password)
    
    new_session = supabase.table('sessions').insert({
        'team_name': team_name,
        'password_hash': password_hash,
        'active': True
    }).execute()
    
    session_id = new_session.data[0]['id']
    print(f"Created new session for team: {team_name}")
    print(f"Session ID: {session_id}")
    return session_id

def join_session(team_name, password):
    response = supabase.table('sessions').select('*').eq('team_name', team_name).execute()
    
    if not response.data or len(response.data) == 0:
        print(f"Error: Team '{team_name}' does not exist")
        return None
    
    session = response.data[0]
    stored_hash = session['password_hash']
    provided_hash = hash_password(password)
    
    if stored_hash != provided_hash:
        print("Error: Incorrect password")
        return None
    
    session_id = session['id']
    
    supabase.table('sessions').update({
        'last_activity': datetime.now().isoformat(),
        'active': True
    }).eq('id', session_id).execute()
    
    print(f"Joined session for team: {team_name}")
    print(f"Session ID: {session_id}")
    return session_id

def end_session(session_id):
    supabase.table('sessions').update({
        'active': False,
        'last_activity': datetime.now().isoformat()
    }).eq('id', session_id).execute()
    print(f"Session {session_id} marked as inactive")

def get_active_sessions():
    response = supabase.table('sessions').select('team_name', 'id', 'created_at', 'last_activity').eq('active', True).execute()
    return response.data

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage:")
        print("  Create: python auth.py create <team_name> <password>")
        print("  Join:   python auth.py join <team_name> <password>")
        sys.exit(1)
    
    action = sys.argv[1]
    team_name = sys.argv[2]
    password = sys.argv[3]
    
    if action == "create":
        session_id = create_session(team_name, password)
    elif action == "join":
        session_id = join_session(team_name, password)
    else:
        print("Invalid action. Use 'create' or 'join'")
        sys.exit(1)
    
    if session_id:
        print(f"\nUse this session_id: {session_id}")