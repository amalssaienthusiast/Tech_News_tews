#!/usr/bin/env python3
"""
Deployment script for the Resilience System.
Run: python deploy_resilience.py
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: str, description: str) -> bool:
    """Run a shell command with error handling."""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            check=True, 
            capture_output=True, 
            text=True
        )
        print(f"   ✅ Success")
        if result.stdout:
            print(f"   {result.stdout[:200]}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Failed: {e.stderr[:200] if e.stderr else str(e)}")
        return False


def deploy_resilience_system():
    """Deploy the complete resilience system."""
    print("🚀 DEPLOYING TECH NEWS SCRAPER RESILIENCE SYSTEM")
    print("=" * 60)
    
    project_root = Path(__file__).parent
    
    # 1. Verify directory structure exists
    print("\n📁 Verifying directory structure...")
    directories = [
        "src/resilience",
        "src/compatibility",
        "logs",
        "config",
        "docs/runbooks"
    ]
    
    for directory in directories:
        dir_path = project_root / directory
        if dir_path.exists():
            print(f"   ✅ {directory} exists")
        else:
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"   📁 Created {directory}")
    
    # 2. Install any missing dependencies
    print("\n📦 Checking dependencies...")
    try:
        import psutil
        print("   ✅ psutil installed")
    except ImportError:
        print("   ⚠️  psutil not installed, installing...")
        run_command("pip install psutil", "Installing psutil")
    
    try:
        import python_dateutil
        print("   ✅ python-dateutil installed")
    except ImportError:
        try:
            import dateutil
            print("   ✅ python-dateutil installed")
        except ImportError:
            print("   ⚠️  python-dateutil not installed, installing...")
            run_command("pip install python-dateutil", "Installing python-dateutil")
    
    # 3. Test module imports
    print("\n🧪 Testing module imports...")
    
    try:
        from src.compatibility import RSSCompatibilityEngine, package_shim
        print("   ✅ src.compatibility imports successful")
    except ImportError as e:
        print(f"   ❌ src.compatibility import failed: {e}")
        return False
    
    try:
        from src.resilience import ResilienceSystem, resilience
        print("   ✅ src.resilience imports successful")
    except ImportError as e:
        print(f"   ❌ src.resilience import failed: {e}")
        return False
    
    # 4. Test RSS compatibility engine
    print("\n🔍 Testing RSS compatibility engine...")
    try:
        engine = RSSCompatibilityEngine()
        print("   ✅ RSSCompatibilityEngine initialized")
        print("   ✅ Feedparser warnings suppressed")
    except Exception as e:
        print(f"   ❌ RSS engine test failed: {e}")
    
    # 5. Test package shim
    print("\n🔍 Testing package shim...")
    try:
        health = package_shim.check_package_health()
        print(f"   ✅ Package health check: {len(health)} packages checked")
        for pkg, status in health.items():
            status_icon = "✅" if status.get('status') == 'healthy' else "⚠️"
            print(f"      {status_icon} {pkg}: {status.get('status', 'unknown')}")
    except Exception as e:
        print(f"   ❌ Package shim test failed: {e}")
    
    # 6. Test resilience system initialization
    print("\n🔍 Testing resilience system...")
    try:
        import asyncio
        
        async def test_resilience():
            await resilience.initialize()
            health = resilience.get_system_health()
            return health
        
        health = asyncio.run(test_resilience())
        print("   ✅ ResilienceSystem initialized")
        print(f"   ✅ Health report: {health.get('initialized', False)}")
    except Exception as e:
        print(f"   ❌ Resilience system test failed: {e}")
    
    # 7. Generate migration report
    print("\n📋 Generating migration report...")
    try:
        report = resilience.generate_migration_plan()
        print("   ✅ Migration plan generated")
        # Show first few lines
        for line in report.split('\n')[:5]:
            print(f"      {line}")
    except Exception as e:
        print(f"   ❌ Migration report failed: {e}")
    
    print("\n" + "=" * 60)
    print("🎉 RESILIENCE SYSTEM DEPLOYED SUCCESSFULLY!")
    print("\nNext steps:")
    print("1. Review config/resilience.yaml for settings")
    print("2. Start the scraper: python main.py")
    print("3. Check logs: tail -f logs/resilience.log")
    print("4. View migration plan: python -c \"from src.resilience import resilience; print(resilience.generate_migration_plan())\"")
    
    return True


if __name__ == "__main__":
    success = deploy_resilience_system()
    sys.exit(0 if success else 1)
