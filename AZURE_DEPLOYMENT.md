# Azure Cloud Deployment Guide

Simple guide to deploy the Event Validation System on Azure Ubuntu VM.

---

## 1. Azure VM Instance

**Instance Type:** Standard_B1s (equivalent to t2.small)
- 1 vCPU, 1 GB RAM
- 20 GB Standard SSD
- Ubuntu 22.04 LTS
- Public IP enabled

---

## 2. Deployment Steps

### Connect to VM

```bash
ssh azureuser@<your-vm-ip>
```

### Install Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip git
python3 -m venv venv
source venv/bin/activate
```

### Clone Repository

```bash
cd ~
git clone https://github.com/hariV0078/MIC.git
cd MIC
```

### Setup Environment

```bash

pip install -r requirements.txt
```

### Create .env File

```bash
nano .env
```
## 4. Environment Variables

**File:** `~/MIC/.env`

```env
export GEMINI_API_KEY=your_gemini_api_key_here
export GROQ_CLOUD_API=your_groq_api_key_here
ACCEPTANCE_THRESHOLD=60
PHASH_THRESHOLD=5
CLEANUP_INTERVAL=3600    # Run cleanup every hour
FILE_MAX_AGE=86400       # Delete files older than 24 hours
MAX_CONCURRENT_API_CALLS=2    # Limit concurrent API calls to avoid rate limits (default: 2)
DEFAULT_MAX_WORKERS=2         # Parallel workers for processing (default: 2)
API_CALL_DELAY=5.0            # Delay between API calls in seconds (default: 5.0)


## 3. Run Application

### Start with nohup

```bash
//inside MIC folder after install requirements
nohup python run_api.py > api.log 2>&1 &
```
```

### Update Application

```bash
restart instance
cd ~/MIC
source venv/bin/activate
git pull origin main
pip install -r requirements.txt

nohup python run_api.py > api.log 2>&1 &
```

---


---


**That's it!** Your application should be running.
