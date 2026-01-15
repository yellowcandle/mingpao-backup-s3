def health_check(ia_client: IAS3Client) -> bool:
    """Perform health checks before starting the backup."""
    console.print("⏳ Running health checks...", style="bold cyan")
    
    # Check IA connectivity and credentials
    try:
        if not ia_client.bucket_exists("test-mingpao-backup"):
            console.print("  ⚠️ Warning: Could not verify existing bucket, but IA S3 endpoint is reachable", style="yellow")
            console.print("  ✅ Internet Archive S3 connection OK", style="green")
    except Exception as e:
        console.print(f"  ❌ Internet Archive connection failed: {e}", style="red")
        return False
    
    # Check Ming Pao website connectivity
    try:
        test_url = "http://www.mingpaocanada.com/tor/htm/News/20250101/HK-gaa1_r.htm"
        response = requests.head(test_url, timeout=10, allow_redirects=False)
        
        if response.status_code in [200, 302, 404]:
            console.print("  ✅ Ming Pao Canada website is reachable", style="green")
            return True
        elif response.status_code < 500:
            console.print("  ✅ Ming Pao Canada website is reachable", style="green")
            return True
        else:
            console.print(f"  ⚠️ Ming Pao Canada returned status {response.status_code}", style="yellow")
            return False
    except Exception as e:
        console.print(f"  ❌ Ming Pao Canada website unreachable: {e}", style="red")
        return False
    
    console.print("  ✅ All health checks passed!", style="green")
    return True