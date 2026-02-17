import subprocess
import sys
import time
import os
import signal
from getpass import getpass

class ConsilienceSystem:
    def __init__(self):
        self.processes = []
        self.session_id = None
    
    def check_redis(self):
        try:
            result = subprocess.run(['redis-cli', 'ping'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=2)
            return result.returncode == 0
        except:
            return False
    
    def start_redis(self):
        print("Starting Redis...")
        try:
            subprocess.Popen(['redis-server', '--daemonize', 'yes'])
            time.sleep(2)
            if self.check_redis():
                print("Redis started successfully")
                return True
            else:
                print("Redis failed to start")
                return False
        except:
            print("Could not start Redis automatically. Please start it manually.")
            return False
    
    def get_session_id(self, action, team_name, password):
        try:
            result = subprocess.run(
                ['python', 'DB/auth.py', action, team_name, password],
                capture_output=True,
                text=True
            )
            
            print(result.stdout)
            
            for line in result.stdout.split('\n'):
                if 'Session ID:' in line:
                    return line.split('Session ID:')[1].strip()
            
            return None
        except Exception as e:
            print(f"Error: {e}")
            return None
    
    def start_process(self, name, command):
        try:
            process = subprocess.Popen(command)
            self.processes.append({'name': name, 'process': process, 'pid': process.pid})
            print(f"Started {name} (PID: {process.pid})")
            return process
        except Exception as e:
            print(f"Failed to start {name}: {e}")
            return None
    
    def stop_all_processes(self):
        print("\n" + "="*70)
        print("Shutting down Consilience System...")
        print("="*70)
        
        for proc_info in reversed(self.processes):
            try:
                print(f"Stopping {proc_info['name']} (PID: {proc_info['pid']})...")
                proc_info['process'].terminate()
                proc_info['process'].wait(timeout=5)
                print(f"{proc_info['name']} stopped")
            except subprocess.TimeoutExpired:
                print(f"Force killing {proc_info['name']}...")
                proc_info['process'].kill()
            except Exception as e:
                print(f"Error stopping {proc_info['name']}: {e}")
        
        print("\nAll processes stopped")
        print("Consilience System shutdown complete.")
    
    def display_system_status(self):
        print("\n" + "="*70)
        print("CONSILIENCE SYSTEM STATUS")
        print("="*70)
        print(f"Session ID: {self.session_id}")
        print(f"\nRunning Processes ({len(self.processes)}):")
        for proc in self.processes:
            status = "Running" if proc['process'].poll() is None else "Stopped"
            print(f"  {proc['name']:<25} PID: {proc['pid']:<8} [{status}]")
        print("="*70)
    
    def launch(self):
        print("="*70)
        print("CONSILIENCE SYSTEM LAUNCHER")
        print("="*70)
        print()
        
        print("Step 1: Checking Redis...")
        if not self.check_redis():
            if not self.start_redis():
                print("\nCannot proceed without Redis. Exiting.")
                return False
        else:
            print("Redis is running")
        
        print()
        
        print("Step 2: Starting background storage worker...")
        worker = self.start_process("Storage Worker", ['python', 'DB/storage.py'])
        if not worker:
            print("Failed to start storage worker. Exiting.")
            return False
        time.sleep(2)
        
        print()
        
        print("Step 3: Session Setup")
        print("-" * 70)
        action = input("Action (create/join): ").strip().lower()
        team_name = input("Team name: ").strip()
        password = getpass("Password: ")
        print("-" * 70)
        
        self.session_id = self.get_session_id(action, team_name, password)
        
        if not self.session_id:
            print("\nFailed to get session ID. Stopping worker...")
            self.stop_all_processes()
            return False
        
        print(f"\nSession established: {self.session_id}")
        print()
        
        print("Step 4: Starting Context Builder...")
        context_builder = self.start_process(
            "Context Builder",
            ['python', 'CONTEXT/context_builder.py', self.session_id]
        )
        if not context_builder:
            print("Failed to start Context Builder. Stopping system...")
            self.stop_all_processes()
            return False
        time.sleep(2)
        
        print()
        
        print("Step 5: Starting Listener...")
        listener = self.start_process(
            "Listener",
            ['python', 'LISTENER/listener.py', self.session_id]
        )
        if not listener:
            print("Failed to start Listener. Stopping system...")
            self.stop_all_processes()
            return False
        time.sleep(2)
        
        print()
        
        print("Step 6: Starting Orchestrator...")
        orchestrator = self.start_process(
            "Orchestrator",
            ['python', 'ORCHESTRATOR/orchestrator.py', self.session_id]
        )
        if not orchestrator:
            print("Failed to start Orchestrator. Stopping system...")
            self.stop_all_processes()
            return False
        time.sleep(2)
        
        print()
        
        print("Step 7: Starting Delivery Monitor...")
        delivery = self.start_process(
            "Delivery Monitor",
            ['python', 'DELIVERY/delivery_monitor.py', self.session_id]
        )
        if not delivery:
            print("Failed to start Delivery Monitor. Stopping system...")
            self.stop_all_processes()
            return False
        time.sleep(2)
        
        print()
        
        print("Step 8: Starting Deepgram STT...")
        print("You can now start speaking!")
        deepgram = self.start_process(
            "Deepgram STT",
            ['python', 'STT/deepgram.py', self.session_id]
        )
        if not deepgram:
            print("Failed to start Deepgram. Stopping system...")
            self.stop_all_processes()
            return False
        
        print()
        
        self.display_system_status()
        
        print("\nAll systems operational!")
        print("\n" + "="*70)
        print("SYSTEM ARCHITECTURE")
        print("="*70)
        print("  Speech Input -> Deepgram -> Storage -> Listener")
        print("                                 |")
        print("                          Context Builder")
        print("                            |         |")
        print("                    Orchestrator <- Context")
        print("                            |")
        print("                    Delivery Monitor")
        print("="*70)
        print("\nStart speaking! Consilience is listening...")
        print("Press Ctrl+C to stop all processes\n")
        
        return True
    
    def monitor(self):
        try:
            while True:
                for proc_info in self.processes:
                    if proc_info['process'].poll() is not None:
                        print(f"\nWARNING: {proc_info['name']} has stopped unexpectedly!")
                
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n\nInterrupt received...")
            self.stop_all_processes()

def main():
    system = ConsilienceSystem()
    
    def signal_handler(sig, frame):
        print("\n\nInterrupt received...")
        system.stop_all_processes()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    if system.launch():
        system.monitor()
    else:
        print("\nSystem launch failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
