import json
import subprocess
from lxml import etree as ET
from zeep import Client
import base64
import requests
from datetime import datetime, timedelta  # timedelta'yı ekledik
import subprocess
import uuid  # UUID oluşturmak için eklendi
import time
import os
from zeep.exceptions import Fault  # Import ekleyelim
import traceback

processed_ka_numbers = set()

def load_processed_ka_numbers():
    try:
        today = datetime.now().strftime("%Y%m%d")
        filename = f'processed_ka_numbers_{today}.json'
        
        cleanup_old_json_files()
        
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return set(json.load(f))
    except Exception as e:
        print(f"Error loading processed KA numbers: {e}")
    return set()

def save_processed_ka_numbers():
    try:
        today = datetime.now().strftime("%Y%m%d")
        filename = f'processed_ka_numbers_{today}.json'
        
        with open(filename, 'w') as f:
            json.dump(list(processed_ka_numbers), f)
    except Exception as e:
        print(f"Error saving processed KA numbers: {e}")

def cleanup_old_json_files():
    try:
        today = datetime.now().strftime("%Y%m%d")
        for file in os.listdir():
            if file.startswith('processed_ka_numbers_') and file.endswith('.json'):
                file_date = file.replace('processed_ka_numbers_', '').replace('.json', '')
                if file_date != today:
                    os.remove(file)
                    print(f"Removed old JSON file: {file}")
    except Exception as e:
        print(f"Error cleaning up old JSON files: {e}")

def get_token():
    url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetToken"
    payload = {
        "Username": "UrartuTrz",
        "Password": "Tsv*57139!"
    }
    response = requests.post(url, json=payload)
    response_data = response.json()
    print("✅ Avis'ten token alındı")
    return response_data['Data']['Token']

def get_invoice_data(license_no):
    url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetInvoiceList"
    today = datetime.now().strftime("%Y%m%d")

    payload = {
        "Token": current_token,
        "LicenseNo": license_no,  # 1 for Avis, 2 for Budget
        "InvoiceDate": "",
        "StartDate": today,
        "EndDate": today
    }
    
    response = requests.post(url, json=payload)
    response_data = response.json()
    
    if response_data.get('MessageEN') == "Token is expired":
        return []
    
    filtered_invoices = []
    today = datetime.now().date()
    cutoff_time = datetime.strptime("16:00:00", "%H:%M:%S").time()

    for invoice in response_data['Data']['Invoices']:
        islem_saati = datetime.fromisoformat(invoice['IslemSaati'])
        if islem_saati.date() == today and islem_saati.time() > cutoff_time:
            filtered_invoices.append(invoice)

    company_name = "Avis" if license_no == 1 else "Budget"
    print(f"✅ {company_name}'ten {len(filtered_invoices)} adet fatura alındı")
    return filtered_invoices

def sayi_to_yazi(sayi):
    birler = ["", "Bir", "İki", "Üç", "Dört", "Beş", "Altı", "Yedi", "Sekiz", "Dokuz"]
    onlar = ["", "On", "Yirmi", "Otuz", "Kırk", "Elli", "Altmış", "Yetmiş", "Seksen", "Doksan"]
    binler = ["", "Bin", "Milyon", "Milyar", "Trilyon", "Katrilyon"]

    def grup_to_yazi(n, basamak):
        yuz = n // 100
        on = (n % 100) // 10
        bir = n % 10
        
        yazi = ""
        if yuz:
            yazi += f"{birler[yuz]} Yüz " if yuz != 1 else "Yüz "
        if on:
            yazi += f"{onlar[on]} "
        if bir:
            yazi += f"{birler[bir]} "
        if yazi and basamak > 0:
            if basamak == 1 and yazi.strip() == "Bir":
                yazi = ""
            yazi += f"{binler[basamak]} "
        return yazi

    if sayi == 0:
        return "Sıfır"

    tam_kisim = int(sayi)
    # Kuruş hesaplamasını düzeltiyoruz
    kurus_kisim = round((sayi - tam_kisim) * 100)  # round kullanarak yuvarlama hatalarını önlüyoruz
    
    print(f"Debug - Tam kısım: {tam_kisim}, Kuruş kısım: {kurus_kisim}")  # Debug için log
    
    yazi = ""
    basamak = 0
    while tam_kisim > 0:
        grup = tam_kisim % 1000
        if grup:
            yazi = grup_to_yazi(grup, basamak) + yazi
        tam_kisim //= 1000
        basamak += 1

    yazi = yazi.strip() + " TL"
    if kurus_kisim:
        kurus_yazi = ""
        on = kurus_kisim // 10
        bir = kurus_kisim % 10
        if on:
            kurus_yazi += f"{onlar[on]} "
        if bir:
            kurus_yazi += f"{birler[bir]} "
        if kurus_yazi:
            yazi += f" {kurus_yazi.strip()} KRŞ"

    return yazi

def update_xml_with_invoice(invoice_data, fatura_tipi=None):
    print("Updating XML with invoice data...")
    print("Invoice data:", json.dumps(invoice_data, indent=4, ensure_ascii=False))

    formatted_invoice_data = {
        'VergiNumarasi': invoice_data.get('VergiNumarasi', ''),
        'TumMusteriAdi': f"(ERTUTECH) {invoice_data.get('TumMusteriAdi', '')}",
        'KDVOrani': invoice_data.get('KDVOrani', 0),
        'KDVTutari': invoice_data.get('KDVTutari', 0),
        'KDVsizTutar': invoice_data.get('KDVsizTutar', 0),
        'KDVliToplamTutar': invoice_data.get('KDVliToplamTutar', 0),
        'KiraGunu': invoice_data.get('KiraGunu', '1'),
        'KANo': invoice_data.get('KANo', ''),
        'Adres': invoice_data.get('Adres', ''),
        'Il': invoice_data.get('Il', ''),
        'Ilce': invoice_data.get('Ilce', ''),
        'VergiDairesi': invoice_data.get('VergiDairesi', ''),
        'KiraTipi': invoice_data.get('KiraTipi', ''),
        'PlakaNo': invoice_data.get('PlakaNo', '')
    }

    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.parse('ornek.xml', parser)
    root = tree.getroot()

    namespaces = {
        'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
        'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
    }

    # Güncel tarih ve saat bilgilerini al
    current_date = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H:%M:%S')

    # Tüm IssueDate elementlerini güncelle
    issue_date_elements = root.findall(".//cbc:IssueDate", namespaces=namespaces)
    for issue_date_element in issue_date_elements:
        issue_date_element.text = current_date
        print(f"IssueDate güncellendi: {current_date}")

    # IssueTime elementini güncelle
    issue_time_element = root.find(".//cbc:IssueTime", namespaces=namespaces)
    if issue_time_element is not None:
        issue_time_element.text = current_time
        print(f"IssueTime güncellendi: {current_time}")

    # Güncellenecek alanlar
    fields_to_update = [
        "Adres", "Il", "Ilce", "VergiDairesi",
        "VergiNumarasi", "KiraTipi"
    ]

    for field in fields_to_update:
        element = root.find(f".//{field}", namespaces=namespaces)
        if element is not None and field in formatted_invoice_data:
            element.text = str(formatted_invoice_data[field])

    # Item altındaki cbc:Name elementini PlakaNo ile güncelle
    item_name_element = root.find(".//cac:Item/cbc:Name", namespaces=namespaces)
    if item_name_element is not None and formatted_invoice_data['PlakaNo']:
        item_name_element.text = f"{formatted_invoice_data['PlakaNo']} PLAKALI ARAÇ KİRALAMA BEDELİ"
        print(f"Plaka güncellendi: {item_name_element.text}")  # Debug için log

    # AccountingCustomerParty güncellemeleri
    accounting_customer_party = root.find(".//cac:AccountingCustomerParty", namespaces=namespaces)
    if accounting_customer_party is not None:
        # PartyName güncelleme
        party_name_element = accounting_customer_party.find(".//cac:PartyName/cbc:Name", namespaces=namespaces)
        if party_name_element is not None:
            party_name_element.text = formatted_invoice_data['TumMusteriAdi']

        # Person güncelleme
        person_element = accounting_customer_party.find(".//cac:Person", namespaces=namespaces)
        if person_element is not None:
            name_parts = formatted_invoice_data['TumMusteriAdi'].split()
            if len(name_parts) > 1:
                first_name_element = person_element.find("cbc:FirstName", namespaces=namespaces)
                if first_name_element is not None:
                    first_name_element.text = " ".join(name_parts[:-1])

                family_name_element = person_element.find("cbc:FamilyName", namespaces=namespaces)
                if family_name_element is not None:
                    family_name_element.text = name_parts[-1]
            else:
                first_name_element = person_element.find("cbc:FirstName", namespaces=namespaces)
                if first_name_element is not None:
                    first_name_element.text = name_parts[0]

                family_name_element = person_element.find("cbc:FamilyName", namespaces=namespaces)
                if family_name_element is not None:
                    family_name_element.text = ""

    # InvoicedQuantity güncelleme
    invoiced_quantity_element = root.find(".//cbc:InvoicedQuantity", namespaces=namespaces)
    if invoiced_quantity_element is not None:
        invoiced_quantity_element.text = str(int(float(formatted_invoice_data['KiraGunu'])))

    # PriceAmount güncelleme
    price_amount_element = root.find(".//cbc:PriceAmount", namespaces=namespaces)
    if price_amount_element is not None:
        try:
            price_per_day = float(formatted_invoice_data['KDVsizTutar']) / float(formatted_invoice_data['KiraGunu'])
            price_amount_element.text = f"{price_per_day:.2f}"
        except ZeroDivisionError:
            price_amount_element.text = "0.00"

    # KDV Oranı güncelleme
    percent_element = root.find(".//cbc:Percent", namespaces=namespaces)
    if percent_element is not None:
        percent_element.text = str(int(formatted_invoice_data['KDVOrani']))

    # TaxAmount güncelleme
    tax_amount_elements = root.findall(".//cbc:TaxAmount", namespaces=namespaces)
    for tax_amount_element in tax_amount_elements:
        tax_amount_element.text = f"{formatted_invoice_data['KDVTutari']:.2f}"

    # KDVsiz tutar ile güncellenecek elementler
    elements_to_update_kdvsiz = [
        ".//cbc:TaxableAmount",
        ".//cbc:LineExtensionAmount",
        ".//cbc:TaxExclusiveAmount"
    ]

    for xpath in elements_to_update_kdvsiz:
        elements = root.findall(xpath, namespaces=namespaces)
        for element in elements:
            if element is not None:
                element.text = str(formatted_invoice_data['KDVsizTutar'])

    # KDVli tutar ile güncellenecek elementler
    elements_to_update_kdvli = [
        ".//cbc:TaxInclusiveAmount",
        ".//cbc:PayableAmount"
    ]

    for xpath in elements_to_update_kdvli:
        element = root.find(xpath, namespaces=namespaces)
        if element is not None:
            element.text = str(formatted_invoice_data['KDVliToplamTutar'])

    # PartyIdentification güncelleme
    party_identification_element = root.find(".//cac:AccountingCustomerParty//cac:PartyIdentification/cbc:ID", namespaces=namespaces)
    if party_identification_element is not None:
        vergi_numarasi = formatted_invoice_data['VergiNumarasi']
        if len(vergi_numarasi) == 11:
            party_identification_element.set("schemeID", "TCKN")
        elif len(vergi_numarasi) == 10:
            party_identification_element.set("schemeID", "VKN")
        party_identification_element.text = vergi_numarasi

    # ProfileID güncelleme
    profile_id_element = root.find(".//cbc:ProfileID", namespaces=namespaces)
    if profile_id_element is not None:
        if fatura_tipi == "EARSIVFATURA":
            profile_id_element.text = "EARSIVFATURA"
        else:
            profile_id_element.text = "TICARIFATURA"

    # UUID güncelleme
    uuid_element = root.find(".//cbc:UUID", namespaces=namespaces)
    if uuid_element is not None:
        new_uuid = str(uuid.uuid4())
        uuid_element.text = new_uuid

    # Toplam tutarı yazıya çevir
    toplam_tutar = float(formatted_invoice_data['KDVliToplamTutar'])
    tutar_yazi = sayi_to_yazi(toplam_tutar)

    # Note elementlerini güncelle
    note_elements = root.findall(".//cbc:Note", namespaces=namespaces)
    if note_elements and len(note_elements) >= 2:
        note_elements[0].text = f"Yazı ile: # {tutar_yazi} #"
        note_elements[1].text = f"KA: {formatted_invoice_data['KANo']}"

    # PostalAddress elementlerini güncelle
    postal_address = root.find(".//cac:AccountingCustomerParty//cac:PostalAddress", namespaces=namespaces)
    if postal_address is not None:
        # BuildingName'i Adres ile güncelle
        building_name = postal_address.find("cbc:BuildingName", namespaces=namespaces)
        if building_name is not None:
            building_name.text = formatted_invoice_data['Adres']

        # CityName'i Il ile güncelle
        city_name = postal_address.find("cbc:CityName", namespaces=namespaces)
        if city_name is not None:
            city_name.text = formatted_invoice_data['Il']

        # CitySubdivisionName'i Ilce ile güncelle
        city_subdivision = postal_address.find("cbc:CitySubdivisionName", namespaces=namespaces)
        if city_subdivision is not None:
            city_subdivision.text = formatted_invoice_data['Ilce']

        print(f"Adres bilgileri güncellendi: {formatted_invoice_data['Adres']}, {formatted_invoice_data['Il']}, {formatted_invoice_data['Ilce']}")  # Debug için log

    tree.write('ornek.xml', pretty_print=True, xml_declaration=True, encoding='UTF-8')
    print("XML file updated successfully.")

def load_invoice(receiver_data):
    print("Loading invoice...")

    # WSDL URL ve Client oluşturma
    wsdl_url = "https://test.edmbilisim.com.tr/EFaturaEDM21ea/EFaturaEDM.svc?wsdl"
    client = Client(wsdl=wsdl_url)
    action_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-1] + "+03:00"

    # Önce Login işlemi yapıp SESSION_ID alalım
    login_request_header = {
        "SESSION_ID": str(uuid.uuid4()),  # Geçici bir SESSION_ID
        "CLIENT_TXN_ID": str(uuid.uuid4()),
        "ACTION_DATE": action_date,
        "REASON": "E-fatura/E-Arşiv gönder-al testleri için",
        "APPLICATION_NAME": "TEST",
        "HOSTNAME": "MDORA17",
        "CHANNEL_NAME": "TEST",
        "COMPRESSED": "N"
    }

    login_request = {
        "REQUEST_HEADER": login_request_header,
        "USER_NAME": "ertutech",
        "PASSWORD": "1234567Edm"
    }

    try:
        print("Logging in...")
        login_response = client.service.Login(**login_request)
        session_id = login_response.SESSION_ID
        print(f"Login successful. Session ID: {session_id}")

        # Create REQUEST_HEADER with the new SESSION_ID
        request_header = {
            "SESSION_ID": session_id,
            "CLIENT_TXN_ID": str(uuid.uuid4()),
            "ACTION_DATE": action_date,
            "REASON": "E-fatura/E-Arşiv gönder-al testleri için",
            "APPLICATION_NAME": "TEST",
            "HOSTNAME": "MDORA17",
            "CHANNEL_NAME": "TEST",
            "COMPRESSED": "N"
        }

        # Global sender and receiver information
        sender = {
            "vkn": "3230512384",
            "alias": "urn:mail:defaultgb@edmbilisim.com.tr"
        }

        # Read the content of ornek.xml and encode it in base64
        with open('ornek.xml', 'rb') as xml_file:
            xml_content = xml_file.read()
            encoded_content = base64.b64encode(xml_content).decode('utf-8')

        # Update the invoice content with the base64 encoded XML
        invoice = {
            "TRXID": "0",
            "HEADER": {
                "SENDER": "3230512384",
                "RECEIVER": receiver_data['vkn'],
                "FROM": "urn:mail:defaultgb@edmbilisim.com.tr",
                "TO": receiver_data['alias'],
                "INTERNETSALES": False,
                "EARCHIVE": False,
                "EARCHIVE_REPORT_SENDDATE": "0001-01-01",
                "CANCEL_EARCHIVE_REPORT_SENDDATE": "0001-01-01",
            },
            "CONTENT": encoded_content
        }

        response = client.service.LoadInvoice(
            REQUEST_HEADER=request_header,
            SENDER=sender,
            RECEIVER=receiver_data,
            INVOICE=[invoice],
            GENERATEINVOICEIDONLOAD=True
        )
        print("LoadInvoice successful:", response)

    except Exception as e:
        print("Error occurred:", str(e))

def check_user(client, session_id, vkn):
    print(f"Checking user with VKN: {vkn}")
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
        print("Sending CheckUser request...")
        response = client.service.CheckUser(REQUEST_HEADER=request_header, USER=user)
        print("CheckUser Response Details:")
        print("-" * 50)
        print(f"Full Response: {response}")
        print("-" * 50)

        # Response boş dizi kontrolü
        if not response or (isinstance(response, list) and len(response) == 0):
            print("Empty response, user is not in e-invoice system")
            return "EARSIVFATURA", None
        else:
            print("User found in e-invoice system")
            # İlk ALIAS değerini al
            alias = response[0].get('ALIAS') if response and len(response) > 0 else None
            return "TICARIFATURA", alias

    except Exception as e:
        print(f"Unexpected error in CheckUser: {str(e)}")
        return "EARSIVFATURA", None

def send_telegram_notification(invoice_data):
    TOKEN = "7846367311:AAEGOEcHElmtmMJfU9GznWEi5ZELfaD4U7Y"
    CHAT_ID = "-1002470063488"
    
    # Mesaj formatını hazırla
    MESSAGE = f"""🧾 Yeni Fatura Eklendi
📝 KA No: {invoice_data.get('KANo', 'N/A')}
👤 Müşteri: {invoice_data.get('TumMusteriAdi', 'N/A')}
🚗 Plaka: {invoice_data.get('PlakaNo', 'N/A')}
💰 Toplam Tutar: {invoice_data.get('KDVliToplamTutar', 'N/A')} TL"""
    
    URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    
    payload = {
        "chat_id": CHAT_ID,
        "text": MESSAGE,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(URL, json=payload)
        data = response.json()
        
        if data.get('ok'):
            print("Telegram notification sent successfully!")
        else:
            print(f"Error sending Telegram notification: {data.get('description', 'Unknown error')}")
            
    except Exception as e:
        print(f"Error sending Telegram notification: {str(e)}")

def send_telegram_error(error_message, ka_no=None):
    TOKEN = "7846367311:AAEGOEcHElmtmMJfU9GznWEi5ZELfaD4U7Y"
    CHAT_ID = "-1002470063488"
    
    # Stack trace'i al ama HTML karakterlerini temizle
    stack_trace = traceback.format_exc()
    # HTML özel karakterlerini escape et
    stack_trace = stack_trace.replace("<", "&lt;").replace(">", "&gt;")
    
    # Mesaj formatını hazırla
    MESSAGE = f"""❌ HATA OLUŞTU!
{'📝 KA No: ' + ka_no if ka_no else ''}
⚠️ Hata Mesajı: {error_message}
🔍 Detaylı Hata:
<pre>{stack_trace}</pre>
⏰ Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    
    payload = {
        "chat_id": CHAT_ID,
        "text": MESSAGE,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(URL, json=payload)
        data = response.json()
        
        if not data.get('ok'):
            print(f"Error sending Telegram error notification: {data.get('description', 'Unknown error')}")
            
    except Exception as e:
        print(f"Error sending Telegram error notification: {str(e)}")

def main_loop():
    global processed_ka_numbers, current_token
    processed_ka_numbers = load_processed_ka_numbers()
    last_token_time = None
    current_token = None
    last_session_time = None
    current_session = None
    current_company = 1  # 1 for Avis, 2 for Budget
    
    while True:
        try:
            current_time = datetime.now()
            
            # Token kontrolü
            if last_token_time is None or (current_time - last_token_time).total_seconds() >= 240:
                current_token = get_token()
                last_token_time = current_time
            
            # Sırayla Avis ve Budget kontrolü
            company_name = "Avis" if current_company == 1 else "Budget"
            invoice_data_list = get_invoice_data(current_company)
            
            if invoice_data_list:
                new_invoices = [
                    invoice for invoice in invoice_data_list 
                    if invoice.get('KANo') not in processed_ka_numbers
                ]
                
                if not new_invoices:
                    print(f"ℹ️ {company_name}'te yeni fatura bulunamadı")
                else:
                    # EDM session kontrolü
                    if last_session_time is None or (current_time - last_session_time).total_seconds() >= 3600:
                        wsdl_url = "https://test.edmbilisim.com.tr/EFaturaEDM21ea/EFaturaEDM.svc?wsdl"
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
                            "USER_NAME": "ertutech",
                            "PASSWORD": "1234567Edm"
                        }

                        login_response = client.service.Login(**login_request)
                        current_session = login_response.SESSION_ID
                        last_session_time = current_time
                        print("✅ EDM'den session alındı")
                    
                    for invoice_data in new_invoices:
                        try:
                            fatura_tipi, alias = check_user(client, current_session, invoice_data['VergiNumarasi'])
                            
                            if fatura_tipi == "TICARIFATURA":
                                receiver_alias = alias
                            else:
                                receiver_alias = invoice_data.get('Email', '-')
                            
                            receiver_data = {
                                "vkn": invoice_data['VergiNumarasi'],
                                "alias": receiver_alias
                            }
                            
                            update_xml_with_invoice(invoice_data, fatura_tipi)
                            load_invoice(receiver_data)
                            print(f"✅ EDM'ye yeni bir {company_name} faturası eklendi (KA No: {invoice_data['KANo']})")
                            
                            send_telegram_notification(invoice_data)
                            processed_ka_numbers.add(invoice_data['KANo'])
                            save_processed_ka_numbers()
                            
                        except Exception as e:
                            send_telegram_error(str(e), invoice_data.get('KANo'))
            
            # Şirket değiştir (1 -> 2 veya 2 -> 1)
            current_company = 2 if current_company == 1 else 1
            
            time.sleep(60)  # Her şirket kontrolü arasında 1 dakika bekle
            
        except Exception as e:
            send_telegram_error(str(e))
            time.sleep(60)

if __name__ == "__main__":
    print("Starting continuous invoice processing...")
    main_loop() 