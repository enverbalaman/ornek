# burası checkuser ve turmob ve xml güncelleme doğru.

from zeep import Client
from zeep.helpers import serialize_object
import uuid
from datetime import datetime, timedelta
import json
import traceback
import base64
import os
import xml.etree.ElementTree as ET
import time
import zeep.exceptions
import random
import requests
import socket

# İşlenmiş faturaları takip etmek için JSON dosyası
PROCESSED_INVOICES_FILE = 'processed_invoices.json'

# Otokoc API token bilgileri
otokoc_token = None
token_expiry_time = None


def get_otokoc_token():
    """Otokoc API'den token alır"""
    global otokoc_token, token_expiry_time
    
    try:
        print("\n🔑 Otokoc API'den token alınıyor...")
        
        # IP bilgilerini al ve göster
        
        
        url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetToken"
        payload = {
            "Username": "UrartuTrz",
            "Password": "Tsv*57139!"
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()  # HTTP hatalarını yakala
        response_data = response.json()
        
        if 'Data' not in response_data or 'Token' not in response_data['Data']:
            print(f"❌ Otokoc API token alınamadı: Geçersiz yanıt formatı")
            print(f"Yanıt: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
            return None
        
        otokoc_token = response_data['Data']['Token']
        # Token geçerlilik süresi 4 dakika
        token_expiry_time = datetime.now() + timedelta(minutes=4)
        print(f"✅ Otokoc API'den token alındı. Geçerlilik: {token_expiry_time.strftime('%H:%M:%S')}")
        return otokoc_token
    except requests.exceptions.RequestException as e:
        print(f"❌ Otokoc API token alma hatası: {str(e)}")
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"❌ Otokoc API token alma hatası: {str(e)}")
        traceback.print_exc()
        return None

def check_and_refresh_token():
    """Token geçerliliğini kontrol eder ve gerekirse yeniler"""
    global otokoc_token, token_expiry_time
    
    if not otokoc_token or not token_expiry_time or datetime.now() >= token_expiry_time:
        print("⚠️ Token geçersiz veya süresi dolmuş, yenileniyor...")
        return get_otokoc_token()
    else:
        remaining_time = (token_expiry_time - datetime.now()).total_seconds()
        print(f"✅ Token geçerli. Kalan süre: {int(remaining_time)} saniye")
        return otokoc_token

def get_invoice_data():
    """Otokoc API'den fatura verilerini çeker"""
    try:
        # Token kontrolü ve yenileme
        token = check_and_refresh_token()
        if not token:
            print("❌ Geçerli token olmadan fatura verileri çekilemez")
            return []
        
        print("\n📊 Otokoc API'den fatura verileri çekiliyor...")
        
        url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetInvoiceList"
        
        # Dünün tarihini al
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        today = datetime.now().strftime("%Y%m%d")
        
        print(f"🗓️ Tarih aralığı: {yesterday} - {today}")

        payload = {
            "Token": token,
            "LicenseNo": 1,
            "InvoiceDate": "",
            "StartDate": yesterday,
            "EndDate": today
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()  # HTTP hatalarını yakala
        response_data = response.json()
        
        if response_data.get('MessageEN') == "Token is expired":
            print("❌ Token süresi dolmuş, yenileniyor...")
            token = get_otokoc_token()
            if not token:
                return []
            
            # Yeni token ile tekrar dene
            payload["Token"] = token
            response = requests.post(url, json=payload)
            response.raise_for_status()
            response_data = response.json()
        
        if 'Data' not in response_data or 'Invoices' not in response_data['Data']:
            print(f"❌ Otokoc API'den fatura verileri çekilemedi: Geçersiz yanıt formatı")
            print(f"Yanıt: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
            return []
        
        invoices = response_data['Data']['Invoices']
        print(f"✅ Otokoc API'den {len(invoices)} fatura verisi çekildi")
        
        # Yanıt formatını kontrol et ve debug için yazdır
        if invoices and len(invoices) > 0:
            print(f"\n🔍 Örnek fatura verisi:")
            print(json.dumps(invoices[0], indent=2, ensure_ascii=False))
            
            # Tüm anahtar alanları listele
            print("\n📋 Fatura veri alanları:")
            for key in invoices[0].keys():
                print(f"   - {key}: {invoices[0][key]}")
        
        # Saat 16:00'dan sonraki faturaları filtrele
        filtered_invoices = []
        for invoice in invoices:
            # IslemSaati alanını kontrol et
            islem_saati = invoice.get('IslemSaati', '')
            if not islem_saati:
                # IslemSaati yoksa alternatif alanları kontrol et
                islem_saati = invoice.get('InvoiceDate', '')
            
            if islem_saati:
                try:
                    # Tarih formatını kontrol et
                    if 'T' in islem_saati:
                        # ISO format: 2025-03-05T16:30:00
                        islem_datetime = datetime.fromisoformat(islem_saati.replace('Z', '+00:00'))
                    else:
                        # Diğer olası formatlar
                        try:
                            islem_datetime = datetime.strptime(islem_saati, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            try:
                                islem_datetime = datetime.strptime(islem_saati, '%d.%m.%Y %H:%M:%S')
                            except ValueError:
                                islem_datetime = datetime.strptime(islem_saati, '%d.%m.%Y')
                    
                    # Saat kontrolü - aynı gün 16:00'dan sonra mı?
                    if islem_datetime.hour >= 16:
                        filtered_invoices.append(invoice)
                        print(f"✅ Fatura kabul edildi: {invoice.get('InvoiceNo', 'N/A')} - İşlem Saati: {islem_saati}")
                    else:
                        print(f"⏭️ Fatura filtrelendi (saat 16:00'dan önce): {invoice.get('InvoiceNo', 'N/A')} - İşlem Saati: {islem_saati}")
                except Exception as e:
                    print(f"⚠️ Tarih dönüştürme hatası ({islem_saati}): {str(e)}")
                    # Hata durumunda faturayı dahil et (isteğe bağlı)
                    filtered_invoices.append(invoice)
            else:
                # İşlem saati bilgisi yoksa faturayı dahil et
                filtered_invoices.append(invoice)
                print(f"⚠️ İşlem saati bilgisi olmayan fatura dahil edildi: {invoice.get('InvoiceNo', 'N/A')}")
        
        print(f"🔍 Filtreleme sonucu: {len(filtered_invoices)}/{len(invoices)} fatura işlenecek")
        
        # Verileri kiralamaVeri.json formatına dönüştür
        formatted_invoices = []
        for invoice in filtered_invoices:
            # InvoiceNo veya KANo alanını kontrol et
            ka_no = invoice.get('InvoiceNo', '')
            if not ka_no:
                ka_no = invoice.get('KANo', '')
                if not ka_no:
                    # Benzersiz bir ID oluştur
                    ka_no = f"AUTO-{str(uuid.uuid4())[:8]}"
                    print(f"⚠️ Fatura numarası bulunamadı, otomatik ID oluşturuldu: {ka_no}")
            
            # VKN alanını kontrol et - VergiNumarasi olarak geliyor
            vkn = invoice.get('VergiNumarasi', '')
            if not vkn:
                # Alternatif alanları kontrol et
                vkn = invoice.get('TaxNo', '')
                if not vkn:
                    vkn = invoice.get('VKN', '')
                    if not vkn:
                        vkn = invoice.get('TCKN', '')
                        if not vkn:
                            # Diğer olası alanları kontrol et
                            for key in invoice.keys():
                                if 'tax' in key.lower() or 'vkn' in key.lower() or 'vergi' in key.lower() or 'tckn' in key.lower():
                                    vkn = invoice[key]
                                    print(f"⚠️ VKN alternatif alandan alındı: {key}")
                                    break
            
            # VKN yoksa uyarı ver
            if not vkn:
                print(f"⚠️ KA No: {ka_no} için VKN bulunamadı")
                # Test için varsayılan VKN atayabilirsiniz
                # vkn = "1234567890"  # Varsayılan bir VKN
            
            formatted_invoice = {
                'KANo': ka_no,
                'VergiNumarasi': vkn,
                'TumMusteriAdi': invoice.get('CustomerName', ''),
                'VergiDairesi': invoice.get('TaxOffice', ''),
                'Adres': invoice.get('Address', ''),
                'Il': invoice.get('City', ''),
                'Ilce': invoice.get('District', ''),
                'KDVOrani': invoice.get('VatRate', 0),
                'KDVTutari': invoice.get('VatAmount', 0),
                'KDVsizTutar': invoice.get('NetAmount', 0),
                'KDVliToplamTutar': invoice.get('GrossAmount', 0),
                'IslemSaati': invoice.get('IslemSaati', '')
            }
            
            formatted_invoices.append(formatted_invoice)
        
        return formatted_invoices
    except requests.exceptions.RequestException as e:
        print(f"❌ Otokoc API fatura verileri çekme hatası: {str(e)}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Otokoc API fatura verileri çekme hatası: {str(e)}")
        traceback.print_exc()
        return []

def edm_login():
    try:
        # Gerçek EDM sistemi
        wsdl_url = "https://portal2.edmbilisim.com.tr/EFaturaEDM/EFaturaEDM.svc?wsdl"
        client = Client(wsdl=wsdl_url)
        
        action_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+03:00"
        login_request_header = {
            "SESSION_ID": str(uuid.uuid4()),
            "CLIENT_TXN_ID": str(uuid.uuid4()),
            "ACTION_DATE": action_date,
            "REASON": "E-fatura/E-Arşiv gönder-al testleri için",
            "APPLICATION_NAME": "EDM MINI CONNECTOR v1.0",
            "HOSTNAME": "MDORA17",
            "CHANNEL_NAME": "TEST",
            "COMPRESSED": "N"
        }

        login_request = {
            "REQUEST_HEADER": login_request_header,
            "USER_NAME": "otomasyon",
            "PASSWORD": "123456789"
        }

        print("\n🔑 EDM Login yapılıyor...")
        login_response = client.service.Login(**login_request)
        session_id = login_response.SESSION_ID
        print(f"✅ EDM Login başarılı - Session ID: {session_id}")
        return client, session_id

    except Exception as e:
        print(f"❌ EDM Login hatası: {str(e)}")
        traceback.print_exc()
        return None, None

def check_user_and_get_info(client, session_id, vkn):
    print("\n" + "="*50)
    print(f"🔍 CheckUser İşlemi Başlatıldı - VKN: {vkn}")
    print("="*50)
    
    action_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+03:00"

    request_header = {
        "SESSION_ID": session_id,
        "CLIENT_TXN_ID": str(uuid.uuid4()),
        "ACTION_DATE": action_date,
        "REASON": "E-fatura/E-Arşiv gönder-al testleri için",
        "APPLICATION_NAME": "EDM MINI CONNECTOR v1.0",
        "HOSTNAME": "MDORA17",
        "CHANNEL_NAME": "TEST",
        "COMPRESSED": "N"
    }

    user = {
        "IDENTIFIER": vkn
    }

    try:
        print("\n📤 CheckUser İsteği Gönderiliyor...")
        print(f"Request Header: {json.dumps(request_header, indent=2)}")
        print(f"User Data: {json.dumps(user, indent=2)}")
        
        response = client.service.CheckUser(REQUEST_HEADER=request_header, USER=user)
        print("\n📥 CheckUser Yanıtı Alındı")
        
        serialized_response = serialize_object(response)
        print("\nCheckUser Response Details:")
        print("-" * 50)
        print(json.dumps(serialized_response, indent=2, ensure_ascii=False))
        print("-" * 50)

        # Response boş dizi kontrolü
        if not response or len(response) == 0:
            print("\n⚠️ Kullanıcı e-fatura sisteminde bulunamadı")
            print("⚠️ E-Arşiv faturası olarak işleme devam edilecek")
            # E-Arşiv için null değerler döndür, alias null olduğunda E-Arşiv olarak işlenecek
            return None, None, None, None, None, None
        
        print("\n✅ Kullanıcı e-fatura sisteminde bulundu")
        
        # Response'un ilk elemanından ALIAS değerini al
        first_user = response[0]
        alias = first_user.ALIAS if hasattr(first_user, 'ALIAS') else None
        print(f"📧 Alias: {alias}")
        
        if not alias:
            print("\n⚠️ Alias bulunamadı")
            print("⚠️ E-Arşiv faturası olarak işleme devam edilecek")
            return None, None, None, None, None, None
            
        # TURMOB bilgilerini al
        print("\n🔄 TURMOB Bilgileri Alınıyor...")
        turmob_header = {
            "SESSION_ID": session_id,
            "CLIENT_TXN_ID": str(uuid.uuid4()),
            "ACTION_DATE": datetime.now().strftime("%Y-%m-%d"),
            "REASON": "test",
            "APPLICATION_NAME": "EDMTEST",
            "HOSTNAME": "BALCIAS",
            "CHANNEL_NAME": "EDM",
            "COMPRESSED": "N"
        }
        
        try:
            print("\n📤 TURMOB İsteği Gönderiliyor...")
            print(f"VKN: {vkn}")
            print(f"Session ID: {session_id}")
            print(f"TURMOB Request Header: {json.dumps(turmob_header, indent=2)}")
            
            try:
                turmob_response = client.service.GetTurmob(REQUEST_HEADER=turmob_header, VKN=vkn)
            except zeep.exceptions.Fault as soap_error:
                print(f"\n❌ SOAP Hatası:")
                print(f"Hata Mesajı: {soap_error.message}")
                if hasattr(soap_error, 'detail'):
                    detail_xml = ET.tostring(soap_error.detail, encoding='unicode')
                    print(f"Hata Detayı XML: {detail_xml}")
                print(f"Hata Kodu: {getattr(soap_error, 'code', 'Kod yok')}")
                return alias, None, None, None, None, None
            
            print("\n📥 TURMOB Ham Yanıt:")
            print("-" * 50)
            print(turmob_response)
            print("-" * 50)
            
            if hasattr(turmob_response, 'ERROR'):
                print(f"\n❌ TURMOB Hatası: {turmob_response.ERROR}")
                return alias, None, None, None, None, None
            
            serialized_turmob = serialize_object(turmob_response)
            print("\n📥 TURMOB Serialize Edilmiş Yanıt:")
            print("-" * 50)
            print(json.dumps(serialized_turmob, indent=2, ensure_ascii=False))
            print("-" * 50)
            
            # Yanıt kontrolü
            if not serialized_turmob:
                print("\n⚠️ TURMOB yanıtı boş")
                return alias, None, None, None, None, None
            
            # TURMOB bilgilerini al
            vergi_dairesi = serialized_turmob.get('vergiDairesiAdi', '')
            unvan = serialized_turmob.get('kimlikUnvani', '')
            
            # Adres bilgileri
            adres_bilgileri = serialized_turmob.get('adresBilgileri', {}).get('AdresBilgileri', [{}])[0]
            
            # Adres bileşenlerini birleştir
            adres_parcalari = [
                adres_bilgileri.get('mahalleSemt', ''),
                adres_bilgileri.get('caddeSokak', ''),
                adres_bilgileri.get('disKapiNo', ''),
                adres_bilgileri.get('icKapiNo', '')
            ]
            tam_adres = ' '.join(filter(None, adres_parcalari))
            il = adres_bilgileri.get('ilAdi', '')
            ilce = adres_bilgileri.get('ilceAdi', '')
            
            print("\n📋 TURMOB Bilgileri:")
            print(f"Vergi Dairesi: {vergi_dairesi}")
            print(f"Unvan: {unvan}")
            print(f"Adres: {tam_adres}")
            print(f"İl: {il}")
            print(f"İlçe: {ilce}")
            
            return alias, vergi_dairesi, unvan, tam_adres, il, ilce
            
        except Exception as e:
            print(f"\n❌ TURMOB bilgileri alınırken hata: {str(e)}")
            traceback.print_exc()
            return alias, None, None, None, None, None

    except Exception as e:
        print(f"\n❌ CheckUser işleminde hata: {str(e)}")
        traceback.print_exc()
        return None, None, None, None, None, None

def send_telegram_notification(message):
    try:
        # Gerçek token ve chat ID'yi kullan (maskelenmiş değil)
        bot_token = "7846367311:AAEGOEcHElmtmMJfU9GznWEi5ZELfaD4U7Y"  # Gerçek token'ı buraya yazın
        chat_id = "-1002470063488"  # Gerçek chat ID'yi buraya yazın
        
        # Debug için token ve chat ID'yi yazdır
        print(f"🔑 Bot Token: {bot_token}")
        print(f"💬 Chat ID: {chat_id}")
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        # Debug için URL'yi yazdır
        print(f"🌐 API URL: {url}")
        
        # İsteği gönder ve yanıtı al
        response = requests.post(url, data=payload)
        
        # Yanıt detaylarını yazdır
        print(f"📡 Telegram API Yanıtı:")
        print(f"Durum Kodu: {response.status_code}")
        print(f"Yanıt İçeriği: {response.text}")
        
        if response.status_code == 200:
            print(f"✅ Telegram bildirimi gönderildi")
        else:
            print(f"❌ Telegram bildirimi gönderilemedi: {response.text}")
            
    except Exception as e:
        print(f"❌ Telegram bildirimi gönderilirken hata: {str(e)}")
        traceback.print_exc()

def update_xml_and_load(client, session_id, vkn, alias, vergi_dairesi, unvan, tam_adres, il, ilce, kayit):
    try:
        # XML şablonunu oku
        with open('ornek.xml', 'r', encoding='utf-8') as f:
            xml_content = f.read()
        
        # Fatura verilerini hazırla
        formatted_invoice_data = {
            'VKN': vkn,
            'Alias': alias,
            'Unvan': unvan or kayit.get('TumMusteriAdi', ''),
            'VergiDairesi': vergi_dairesi or kayit.get('VergiDairesi', ''),
            'KiraTipi': kayit.get('KiraTipi', ''),
            'PlakaNo': kayit.get('PlakaNo', ''),
            'IslemSaati': kayit.get('IslemSaati', '')
        }
        
        # Adres bilgilerini ekle
        formatted_invoice_data['TamAdres'] = tam_adres or kayit.get('Adres', '')
        formatted_invoice_data['Il'] = il or kayit.get('Il', '')
        formatted_invoice_data['Ilce'] = ilce or kayit.get('Ilce', '')
        
        # Tutar bilgilerini ekle
        kdv_orani = kayit.get('KDVOrani', 0)
        kdv_tutari = kayit.get('KDVTutari', 0)
        kdvsiz_tutar = kayit.get('KDVsizTutar', 0)
        kdvli_toplam_tutar = kayit.get('KDVliToplamTutar', 0)
        kira_gunu = kayit.get('KiraGunu', '1')
        
        formatted_invoice_data['KDVOrani'] = kdv_orani
        formatted_invoice_data['KDVTutari'] = kdv_tutari
        formatted_invoice_data['KDVsizTutar'] = kdvsiz_tutar
        formatted_invoice_data['KDVliToplamTutar'] = kdvli_toplam_tutar
        formatted_invoice_data['KiraGunu'] = kira_gunu
        
        # KA No ekle
        formatted_invoice_data['KANo'] = kayit.get('KANo', '')
        
        print(f"✅ Fatura verileri hazırlandı: {json.dumps(formatted_invoice_data, indent=2, ensure_ascii=False)}")
        
        # XML içeriğini güncelle
        tree = ET.fromstring(xml_content)
        
        # Müşteri bilgilerini güncelle
        for party in tree.findall(".//cac:AccountingCustomerParty/cac:Party", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'}):
            # Unvan güncelle
            for name in party.findall(".//cac:PartyName/cbc:Name", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2', 'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                name.text = formatted_invoice_data['Unvan']
            
            # VKN güncelle
            for id_elem in party.findall(".//cac:PartyIdentification/cbc:ID", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2', 'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                if id_elem.get('schemeID') == 'VKN':
                    id_elem.text = formatted_invoice_data['VKN']
            
            # Vergi dairesi güncelle
            for tax_scheme in party.findall(".//cac:PartyTaxScheme/cac:TaxScheme/cbc:Name", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2', 'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                tax_scheme.text = formatted_invoice_data['VergiDairesi']
            
            # Adres bilgilerini güncelle
            for address in party.findall(".//cac:PostalAddress", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'}):
                for street_name in address.findall("./cbc:StreetName", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                    street_name.text = formatted_invoice_data['TamAdres']
                
                for city_name in address.findall("./cbc:CityName", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                    city_name.text = formatted_invoice_data['Il']
                
                for district in address.findall("./cbc:CitySubdivisionName", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                    district.text = formatted_invoice_data['Ilce']
        
        # Tutar bilgilerini güncelle
        # KDV tutarı
        for tax_amount in tree.findall(".//cac:TaxTotal/cbc:TaxAmount", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2', 'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
            tax_amount.text = str(kdv_tutari)
        
        # KDV oranı
        for percent in tree.findall(".//cac:TaxSubtotal/cac:TaxCategory/cbc:Percent", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2', 'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
            percent.text = str(kdv_orani)
        
        # KDV'siz tutar
        for taxable_amount in tree.findall(".//cac:TaxSubtotal/cbc:TaxableAmount", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2', 'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
            taxable_amount.text = str(kdvsiz_tutar)
        
        # KDV tutarı (TaxSubtotal altında)
        for tax_amount in tree.findall(".//cac:TaxSubtotal/cbc:TaxAmount", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2', 'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
            tax_amount.text = str(kdv_tutari)
        
        # Toplam tutar
        for legal_monetary_total in tree.findall(".//cac:LegalMonetaryTotal", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'}):
            # KDV'siz tutar
            for line_extension_amount in legal_monetary_total.findall("./cbc:LineExtensionAmount", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                line_extension_amount.text = str(kdvsiz_tutar)
            
            # KDV'siz tutar (TaxExclusiveAmount)
            for tax_exclusive_amount in legal_monetary_total.findall("./cbc:TaxExclusiveAmount", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                tax_exclusive_amount.text = str(kdvsiz_tutar)
            
            # KDV'li toplam tutar
            for tax_inclusive_amount in legal_monetary_total.findall("./cbc:TaxInclusiveAmount", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                tax_inclusive_amount.text = str(kdvli_toplam_tutar)
            
            # Ödenecek tutar
            for payable_amount in legal_monetary_total.findall("./cbc:PayableAmount", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                payable_amount.text = str(kdvli_toplam_tutar)
        
        # Kalem bilgilerini güncelle
        for invoice_line in tree.findall(".//cac:InvoiceLine", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'}):
            # Kalem tutarı
            for line_extension_amount in invoice_line.findall("./cbc:LineExtensionAmount", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                line_extension_amount.text = str(kdvsiz_tutar)
            
            # Birim fiyat
            for price_amount in invoice_line.findall("./cac:Price/cbc:PriceAmount", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2', 'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                price_amount.text = str(kdvsiz_tutar)
            
            # Miktar (kira günü)
            for quantity in invoice_line.findall("./cbc:InvoicedQuantity", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'}):
                quantity.text = str(kira_gunu)
        
        # KDV tutarı 0 ise, istisna sebebi ekle
        for tax_subtotal in tree.findall(".//cac:TaxSubtotal", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'}):
            tax_amount = tax_subtotal.find("./cbc:TaxAmount", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'})
            tax_category = tax_subtotal.find("./cac:TaxCategory", namespaces={'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'})
            
            if tax_amount is not None and float(tax_amount.text) == 0:
                # KDV tutarı 0 ise ve TaxExemptionReason elemanı yoksa ekle
                tax_exemption_reason = tax_category.find("./cbc:TaxExemptionReason", namespaces={'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'})
                
                if tax_exemption_reason is None:
                    # TaxExemptionReason elemanı oluştur
                    tax_exemption_reason = ET.SubElement(tax_category, "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxExemptionReason")
                    tax_exemption_reason.text = "KDV İstisnası"
                    print("✅ KDV tutarı 0 olduğu için TaxExemptionReason elemanı eklendi")
        
        # Güncellenmiş XML'i kaydet
        updated_xml = ET.tostring(tree, encoding='utf-8', method='xml').decode('utf-8')
        with open('updated_invoice.xml', 'w', encoding='utf-8') as f:
            f.write(updated_xml)
        
        print("✅ XML başarıyla güncellendi ve kaydedildi")
        
        # Base64 kodlaması
        base64_xml = base64.b64encode(updated_xml.encode('utf-8')).decode('utf-8')
        
        # Faturayı yükle
        load_params = {
            'sessionId': session_id,
            'xmlContent': base64_xml,
            'sourceUrn': alias,
            'compressed': False
        }
        
        try:
            response = client.service.LoadInvoice(**load_params)
            
            if response and hasattr(response, 'IsSucceeded') and response.IsSucceeded:
                print(f"\n✅ Fatura başarıyla yüklendi: {response.Message}")
                
                # Başarılı işlemi kaydet
                ka_no = formatted_invoice_data.get('KANo', '')
                if ka_no:
                    save_processed_invoice(ka_no)
                
                # Başarılı işlem bildirimi
                success_notification = f"""
<b>✅ Fatura Başarıyla Yüklendi</b>

<b>Fatura Bilgileri:</b>
🔹 <b>VKN/TCKN:</b> {vkn}
🔹 <b>Müşteri:</b> {unvan}
🔹 <b>KA No:</b> {formatted_invoice_data.get('KANo', 'Bilinmiyor')}

<b>Tutar Bilgileri:</b>
🔹 <b>KDV Oranı:</b> %{kdv_orani}
🔹 <b>KDV Tutarı:</b> {kdv_tutari} TL
🔹 <b>KDV'siz Tutar:</b> {kdvsiz_tutar} TL
🔹 <b>Toplam Tutar:</b> {kdvli_toplam_tutar} TL

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
                send_telegram_notification(success_notification)
                
                return True
            else:
                error_message = response.Message if hasattr(response, 'Message') else "Bilinmeyen hata"
                print(f"\n❌ Fatura yüklenemedi: {error_message}")
                
                # Hata bildirimi
                error_notification = f"""
<b>❌ Fatura Yükleme Hatası</b>

<b>Fatura Bilgileri:</b>
🔹 <b>VKN/TCKN:</b> {vkn}
🔹 <b>Müşteri:</b> {unvan}
🔹 <b>KA No:</b> {formatted_invoice_data.get('KANo', 'Bilinmiyor')}

<b>Hata Mesajı:</b>
{error_message}

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
                send_telegram_notification(error_notification)
                
                return False
        except zeep.exceptions.Fault as e:
            print(f"\n❌ LoadInvoice hatası: {str(e)}")
            traceback.print_exc()
            
            # Hata bildirimi
            error_notification = f"""
<b>❌ Fatura Yükleme Hatası (SOAP)</b>

<b>Fatura Bilgileri:</b>
🔹 <b>VKN/TCKN:</b> {vkn}
🔹 <b>Müşteri:</b> {unvan}
🔹 <b>KA No:</b> {formatted_invoice_data.get('KANo', 'Bilinmiyor')}

<b>Hata Mesajı:</b>
{str(e)}

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
            send_telegram_notification(error_notification)
            
            return False
    except Exception as e:
        print(f"\n❌ XML güncelleme hatası: {str(e)}")
        traceback.print_exc()
        
        # Hata bildirimi
        error_notification = f"""
<b>❌ XML Güncelleme Hatası</b>

<b>Hata Mesajı:</b>
{str(e)}

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(error_notification)
        
        return False

# Sayıyı yazıya çeviren fonksiyon
def sayi_to_yazi(sayi):
    birler = ["", "BİR", "İKİ", "ÜÇ", "DÖRT", "BEŞ", "ALTI", "YEDİ", "SEKİZ", "DOKUZ"]
    onlar = ["", "ON", "YİRMİ", "OTUZ", "KIRK", "ELLİ", "ALTMIŞ", "YETMİŞ", "SEKSEN", "DOKSAN"]
    
    def yuzler_to_yazi(n):
        if n == 0:
            return ""
        elif n < 10:
            return birler[n]
        elif n < 100:
            return onlar[n // 10] + " " + birler[n % 10]
        else:
            if n // 100 == 1:
                return "YÜZ " + yuzler_to_yazi(n % 100)
            else:
                return birler[n // 100] + " YÜZ " + yuzler_to_yazi(n % 100)
    
    def binler_to_yazi(n):
        if n < 1000:
            return yuzler_to_yazi(n)
        elif n < 1000000:
            if n // 1000 == 1:
                return "BİN " + yuzler_to_yazi(n % 1000)
            else:
                return yuzler_to_yazi(n // 1000) + " BİN " + yuzler_to_yazi(n % 1000)
        else:
            return yuzler_to_yazi(n // 1000000) + " MİLYON " + binler_to_yazi(n % 1000000)
    
    # Sayıyı tam ve kuruş olarak ayır
    tam_kisim = int(sayi)
    kurus_kisim = int((sayi - tam_kisim) * 100 + 0.5)  # Yuvarlama
    
    # Tam kısmı yazıya çevir
    tam_yazi = binler_to_yazi(tam_kisim).strip()
    
    # Kuruş kısmı yazıya çevir
    kurus_yazi = yuzler_to_yazi(kurus_kisim).strip()
    
    # Sonucu birleştir
    if tam_kisim > 0 and kurus_kisim > 0:
        return f"{tam_yazi} TÜRK LİRASI {kurus_yazi} KURUŞ"
    elif tam_kisim > 0:
        return f"{tam_yazi} TÜRK LİRASI"
    elif kurus_kisim > 0:
        return f"{kurus_yazi} KURUŞ"
    else:
        return "SIFIR TÜRK LİRASI"

# İşlenmiş faturaları yükle
def load_processed_invoices():
    try:
        if os.path.exists(PROCESSED_INVOICES_FILE):
            with open(PROCESSED_INVOICES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {"processed_invoices": [], "last_check_time": None}
    except Exception as e:
        print(f"❌ İşlenmiş faturalar yüklenirken hata: {str(e)}")
        return {"processed_invoices": [], "last_check_time": None}

# İşlenmiş faturaları kaydet
def save_processed_invoice(ka_no):
    try:
        processed_data = load_processed_invoices()
        
        # KA numarası zaten işlenmişse ekleme
        if ka_no not in processed_data["processed_invoices"]:
            processed_data["processed_invoices"].append(ka_no)
        
        # Son kontrol zamanını güncelle
        processed_data["last_check_time"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(PROCESSED_INVOICES_FILE, 'w', encoding='utf-8') as f:
            json.dump(processed_data, indent=2, ensure_ascii=False, fp=f)
        
        print(f"✅ KA No: {ka_no} işlenmiş faturalar listesine eklendi")
        return True
    except Exception as e:
        print(f"❌ İşlenmiş fatura kaydedilirken hata: {str(e)}")
        return False

def process_new_invoices():
    try:
        # Önce işlenmiş faturaları yükle
        processed_data = load_processed_invoices()
        processed_invoices = processed_data["processed_invoices"]
        
        # Otokoc API'den fatura verilerini çek
        invoice_data = get_invoice_data()
        
        if not invoice_data:
            print("⚠️ İşlenecek fatura verisi bulunamadı")
            return
        
        # İşlenmemiş faturaları filtrele
        unprocessed_invoices = []
        for kayit in invoice_data:
            ka_no = kayit.get('KANo', '')
            if ka_no and ka_no not in processed_invoices:
                unprocessed_invoices.append(kayit)
                print(f"✅ İşlenecek yeni fatura: KA No: {ka_no}")
            elif ka_no in processed_invoices:
                print(f"⏭️ Fatura zaten işlenmiş: KA No: {ka_no}")
            else:
                print(f"⚠️ KA No bulunamadı, fatura atlanıyor")
        
        if not unprocessed_invoices:
            print(f"\n✅ İşlenecek yeni fatura bulunamadı. Toplam işlenmiş fatura: {len(processed_invoices)}")
            return
        
        # Yeni faturalar varsa EDM'ye bağlan
        print(f"\n📋 Toplam {len(unprocessed_invoices)} yeni kayıt işlenecek")
        
        # EDM'ye bağlan
        client, session_id = edm_login()
        if not client or not session_id:
            print("❌ EDM bağlantısı başarısız!")
            
            # Bağlantı hatası bildirimi
            error_notification = f"""
<b>❌ EDM Bağlantı Hatası</b>

<b>Hata Mesajı:</b>
EDM sistemine bağlanılamadı.

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
            send_telegram_notification(error_notification)
            return
        
        # İşlem başlangıç bildirimi
        start_notification = f"""
<b>🚀 Yeni Fatura İşlemleri Başlatıldı</b>

<b>Toplam İşlenecek Kayıt:</b> {len(unprocessed_invoices)}
<b>Başlangıç Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(start_notification)
        
        # Başarılı ve başarısız işlem sayaçları
        success_count = 0
        fail_count = 0

        # Her kayıt için işlem yap
        for index, kayit in enumerate(unprocessed_invoices, 1):
            vkn = kayit.get('VergiNumarasi')  # VergiNumarasi alanını kullan
            ka_no = kayit.get('KANo', 'Bilinmiyor')
            
            print(f"\n{'='*50}")
            print(f"🔄 Kayıt {index}/{len(unprocessed_invoices)} işleniyor")
            print(f"📝 VKN: {vkn}, KA No: {ka_no}")
            print(f"{'='*50}")

            if not vkn:
                print("⚠️ VKN bulunamadı, varsayılan VKN kullanılacak")
                # Varsayılan VKN kullan (test için)
                vkn = "1234567890"  # Varsayılan bir VKN
                
                # Veya alternatif olarak, bu kaydı atla
                # print("❌ VKN bulunamadı, kayıt atlanıyor")
                # fail_count += 1
                # continue

            # Firma bilgilerini kontrol et
            alias, vergi_dairesi, unvan, tam_adres, il, ilce = check_user_and_get_info(client, session_id, vkn)
            
            # E-fatura mükellefi değilse veya bilgiler alınamadıysa API'den gelen bilgileri kullan
            if not alias:
                print(f"\n⚠️ VKN: {vkn} - Firma e-fatura mükellefi değil, E-Arşiv faturası olarak işlenecek")
                # API'den gelen bilgileri kullan
                unvan = kayit.get('TumMusteriAdi', '')
                vergi_dairesi = kayit.get('VergiDairesi', '')
                tam_adres = kayit.get('Adres', '')
                il = kayit.get('Il', '')
                ilce = kayit.get('Ilce', '')
            else:
                print(f"\n✅ VKN: {vkn} - Firma e-fatura mükellefi, E-Fatura olarak işlenecek")

            print("\n📋 Firma Bilgileri:")
            print(f"Unvan: {unvan}")
            print(f"VKN: {vkn}")
            print(f"Alias: {alias}")
            print(f"Vergi Dairesi: {vergi_dairesi}")
            print(f"Adres: {tam_adres}")
            print(f"İl: {il}")
            print(f"İlçe: {ilce}")
            print(f"KA No: {ka_no}")

            # TURMOB'dan gelen adres bilgileri null ise API'den gelen bilgileri kullan
            if not tam_adres or not il or not ilce:
                print("\n⚠️ Adres bilgileri eksik, API'den gelen bilgiler kullanılıyor")
                tam_adres = kayit.get('Adres', '')
                il = kayit.get('Il', '')
                ilce = kayit.get('Ilce', '')

            # XML güncelle ve faturayı yükle - kayıt verisini de gönder
            if update_xml_and_load(client, session_id, vkn, alias, vergi_dairesi, unvan, tam_adres, il, ilce, kayit):
                print(f"\n✅ VKN: {vkn}, KA No: {ka_no} - İşlem başarıyla tamamlandı")
                success_count += 1
            else:
                print(f"\n❌ VKN: {vkn}, KA No: {ka_no} - İşlem başarısız")
                fail_count += 1

            # İşlemler arası kısa bekle
            time.sleep(1)

        print("\n✅ Tüm yeni kayıtlar işlendi")
        
        # İşlem sonuç bildirimi
        end_notification = f"""
<b>🏁 Yeni Fatura İşlemleri Tamamlandı</b>

<b>Sonuç Özeti:</b>
🔹 <b>Toplam İşlenen Kayıt:</b> {len(unprocessed_invoices)}
🔹 <b>Başarılı İşlem:</b> {success_count}
🔹 <b>Başarısız İşlem:</b> {fail_count}
🔹 <b>Toplam İşlenmiş Fatura:</b> {len(processed_data["processed_invoices"]) + success_count}

<b>Bitiş Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(end_notification)

    except Exception as e:
        print(f"\n❌ Genel hata: {str(e)}")
        traceback.print_exc()
        
        # Genel hata bildirimi
        error_notification = f"""
<b>❌ Genel Hata</b>

<b>Hata Mesajı:</b>
{str(e)}

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(error_notification)

def main():
    try:
        print("\n🔄 Fatura işleme servisi başlatıldı")
        
        # Başlangıçta IP bilgilerini göster
        ip_info = get_my_ip()
        if ip_info:
            print(f"\n📡 Sistem IP Bilgileri:")
            print(f"   🌐 Dış IP: {ip_info['external_ip']}")
            print(f"   🏠 Yerel IP: {ip_info['local_ip']}")
            print(f"   💻 Hostname: {ip_info['hostname']}")
        
        send_telegram_notification("<b>🚀 Fatura İşleme Servisi Başlatıldı</b>")
        
        # İlk token'ı al
        if not get_otokoc_token():
            print("❌ Otokoc API token alınamadı, servis başlatılamıyor")
            send_telegram_notification("<b>❌ Otokoc API token alınamadı, servis başlatılamıyor</b>")
            return
        
        # İlk çalıştırmada tüm faturaları işle
        process_new_invoices()
        
        # Her 1 dakikada bir yeni faturaları kontrol et
        while True:
            print(f"\n⏳ Bir sonraki kontrol için bekleniyor... ({datetime.now().strftime('%H:%M:%S')})")
            time.sleep(60)  # 60 saniye bekle
            print(f"\n🔍 Yeni faturalar kontrol ediliyor... ({datetime.now().strftime('%H:%M:%S')})")
            
            # Token kontrolü
            check_and_refresh_token()
            
            # Yeni faturaları işle
            process_new_invoices()
            
    except KeyboardInterrupt:
        print("\n⚠️ Kullanıcı tarafından durduruldu")
        send_telegram_notification("<b>⚠️ Fatura İşleme Servisi Durduruldu</b>")
    except Exception as e:
        print(f"\n❌ Ana döngüde hata: {str(e)}")
        traceback.print_exc()
        
        error_notification = f"""
<b>❌ Fatura İşleme Servisi Hatası</b>

<b>Hata Mesajı:</b>
{str(e)}

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(error_notification)

if __name__ == "__main__":
    main()