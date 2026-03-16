import requests
import time

def test_api():
    url = "http://127.0.0.1:8000/api/stations"
    print(f"Testing {url}...")
    try:
        start_time = time.time()
        response = requests.get(url, timeout=5)
        duration = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            print(f"Success! Status: {response.status_code}")
            print(f"Count: {len(data)} stations")
            print(f"Duration: {duration:.4f} seconds")
            if len(data) > 0:
                print(f"Sample: {data[0]['name']}")
        else:
            print(f"Failed. Status: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"Error connecting to server: {e}")

if __name__ == "__main__":
    test_api()
