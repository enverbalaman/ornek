import requests
import json
from datetime import datetime, timedelta
import os
import traceback

# Sabit değişkenler
LOG_DIRECTORY = 'data_logs'
DATA_DIRECTORY = 'collected_data'
SERVER_TIME_DIFFERENCE = 3  # Sunucu ve yerel saat farkı (saat cinsinden)

def get_local_time():
    """Sunucu saatinden yerel saati hesaplar (3 saat ileri)"""
    return datetime.now() + timedelta(hours=SERVER_TIME_DIFFERENCE)

def ensure_directories():
    """Log ve veri klasörlerinin varlığını kontrol eder ve yoksa oluşturur"""
    for directory in [LOG_DIRECTORY, DATA_DIRECTORY]:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"✅ Klasör oluşturuldu: {directory}")

def get_otokoc_token():
    """Otokoc API'den token alır"""
    try:
        print("\n🔑 Otokoc API'den token alınıyor...")
        
        url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetToken"
        payload = {
            "Username": "UrartuTrz",
            "Password": "Tsv*57139!"
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        response_data = response.json()
        
        if 'Data' not in response_data or 'Token' not in response_data['Data']:
            print(f"❌ Otokoc API token alınamadı: Geçersiz yanıt formatı")
            return None
        
        token = response_data['Data']['Token']
        print(f"✅ Otokoc API'den token alındı")
        return token
        
    except Exception as e:
        print(f"❌ Otokoc API token alma hatası: {str(e)}")
        traceback.print_exc()
        return None

def get_invoice_data(token, license_no):
    """Otokoc API'den fatura verilerini çeker"""
    try:
        company_name = "Avis" if license_no == 1 else "Budget"
        print(f"\n📊 Otokoc API'den {company_name} fatura verileri çekiliyor...")
        
        url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetInvoiceList"
        
        # Yerel zamana göre dün ve bugün
        local_now = get_local_time()
        yesterday = (local_now - timedelta(days=1)).strftime("%Y%m%d")
        today = local_now.strftime("%Y%m%d")
        
        print(f"🗓️ Tarih aralığı: {yesterday} - {today}")
        
        payload = {
            "Token": token,
            "LicenseNo": license_no,  # 1 for Avis, 2 for Budget
            "InvoiceDate": "",
            "StartDate": yesterday,
            "EndDate": today
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        response_data = response.json()
        
        if 'Data' not in response_data or 'Invoices' not in response_data['Data']:
            print(f"❌ Otokoc API {company_name} fatura verileri çekilemedi: Geçersiz yanıt formatı")
            return []
        
        invoices = response_data['Data']['Invoices']
        print(f"✅ Otokoc API'den {len(invoices)} {company_name} fatura verisi çekildi")
        
        return invoices
        
    except Exception as e:
        print(f"❌ Otokoc API {company_name} fatura verileri çekme hatası: {str(e)}")
        traceback.print_exc()
        return []

def save_data_to_json(avis_data, budget_data):
    """Verileri JSON dosyasına kaydeder"""
    try:
        local_now = get_local_time()
        filename = os.path.join(DATA_DIRECTORY, f"invoice_data_{local_now.strftime('%Y%m%d_%H%M%S')}.json")
        
        data = {
            "collection_time": local_now.strftime('%Y-%m-%d %H:%M:%S'),
            "avis": {
                "count": len(avis_data),
                "invoices": avis_data
            },
            "budget": {
                "count": len(budget_data),
                "invoices": budget_data
            }
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        print(f"\n✅ Veriler kaydedildi: {filename}")
        return True
        
    except Exception as e:
        print(f"❌ Veri kaydetme hatası: {str(e)}")
        traceback.print_exc()
        return False

def save_log(avis_count, budget_count):
    """İşlem logunu kaydeder"""
    try:
        local_now = get_local_time()
        log_file = os.path.join(LOG_DIRECTORY, f"data_collection_log_{local_now.strftime('%Y%m%d')}.json")
        
        # Mevcut logları yükle veya yeni log listesi oluştur
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        else:
            logs = {"logs": []}
        
        # Yeni log kaydı
        log_entry = {
            "timestamp": local_now.strftime('%Y-%m-%d %H:%M:%S'),
            "avis_count": avis_count,
            "budget_count": budget_count,
            "total_count": avis_count + budget_count
        }
        
        logs["logs"].append(log_entry)
        
        # Logları kaydet
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
            
        print(f"\n✅ Log kaydedildi: {log_file}")
        return True
        
    except Exception as e:
        print(f"❌ Log kaydetme hatası: {str(e)}")
        traceback.print_exc()
        return False

def main():
    try:
        print("\n🚀 Veri toplama işlemi başlatılıyor...")
        local_now = get_local_time()
        print(f"📅 Yerel Saat: {local_now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Klasörleri kontrol et
        ensure_directories()
        
        # Token al
        token = get_otokoc_token()
        if not token:
            print("❌ Token alınamadığı için işlem sonlandırılıyor")
            return
        
        # Avis verilerini çek
        avis_data = get_invoice_data(token, 1)
        print(f"\n📊 Avis fatura sayısı: {len(avis_data)}")
        
        # Budget verilerini çek
        budget_data = get_invoice_data(token, 2)
        print(f"📊 Budget fatura sayısı: {len(budget_data)}")
        
        # Verileri JSON dosyasına kaydet
        if save_data_to_json(avis_data, budget_data):
            print("✅ Veriler başarıyla JSON dosyasına kaydedildi")
        else:
            print("❌ Veriler JSON dosyasına kaydedilemedi")
        
        # Log kaydet
        if save_log(len(avis_data), len(budget_data)):
            print("✅ Log başarıyla kaydedildi")
        else:
            print("❌ Log kaydedilemedi")
        
        print("\n✅ Veri toplama işlemi tamamlandı")
        
    except Exception as e:
        print(f"\n❌ Genel hata: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main() 