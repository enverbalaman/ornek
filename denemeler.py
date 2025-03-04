from zeep import Client
from zeep.helpers import serialize_object
import uuid
from datetime import datetime
import json
import traceback
import base64
import os
import xml.etree.ElementTree as ET
import time
import zeep.exceptions
import random
import requests
import logging

# Logging yapılandırması
logging.basicConfig(
    filename='invoice_processing.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
        logging.error(f"Error loading processed KA numbers: {e}")
    return set()

def save_processed_ka_numbers():
    try:
        today = datetime.now().strftime("%Y%m%d")
        filename = f'processed_ka_numbers_{today}.json'
        
        with open(filename, 'w') as f:
            json.dump(list(processed_ka_numbers), f)
    except Exception as e:
        logging.error(f"Error saving processed KA numbers: {e}")

def cleanup_old_json_files():
    try:
        today = datetime.now().strftime("%Y%m%d")
        for file in os.listdir():
            if file.startswith('processed_ka_numbers_') and file.endswith('.json'):
                file_date = file.replace('processed_ka_numbers_', '').replace('.json', '')
                if file_date != today:
                    os.remove(file)
                    logging.info(f"Removed old JSON file: {file}")
    except Exception as e:
        logging.error(f"Error cleaning up old JSON files: {e}")

def get_token():
    url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetToken"
    payload = {
        "Username": "UrartuTrz",
        "Password": "Tsv*57139!"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        response_data = response.json()
        logging.info("✅ Avis'ten token alındı")
        return response_data['Data']['Token']
    except requests.exceptions.RequestException as e:
        logging.error(f"Error getting token: {e}")
        return None

def get_invoice_data(license_no):
    url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetInvoiceList"
    
    # 3 Mart 2025 tarihini ve saat 17:00'ı belirle
    start_date = "20250303"
    cutoff_time = datetime.strptime("12:00:00", "%H:%M:%S").time()

    payload = {
        "Token": current_token,
        "LicenseNo": license_no,
        "InvoiceDate": "",
        "StartDate": start_date,
        "EndDate": start_date
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        response_data = response.json()
        
        if response_data.get('MessageEN') == "Token is expired":
            logging.warning("Token is expired")
            return []
        
        filtered_invoices = []
        for invoice in response_data['Data']['Invoices']:
            islem_saati = datetime.fromisoformat(invoice['IslemSaati'])
            # Tarih ve saat kontrolü
            if islem_saati.date() == datetime.strptime(start_date, "%Y%m%d").date() and islem_saati.time() > cutoff_time:
                filtered_invoices.append(invoice)

        company_name = "Avis" if license_no == 1 else "Budget"
        logging.info(f"✅ {company_name}'ten {len(filtered_invoices)} adet fatura alındı")
        return filtered_invoices
    except requests.exceptions.RequestException as e:
        logging.error(f"Error getting invoice data: {e}")
        return []

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
    kurus_kisim = round((sayi - tam_kisim) * 100)
    
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
    try:
        print("Updating XML with invoice data...")
        logging.info(f"Updating XML with invoice data: {invoice_data}")

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
            logging.info(f"IssueDate güncellendi: {current_date}")

        # IssueTime elementini güncelle
        issue_time_element = root.find(".//cbc:IssueTime", namespaces=namespaces)
        if issue_time_element is not None:
            issue_time_element.text = current_time
            logging.info(f"IssueTime güncellendi: {current_time}")

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
            logging.info(f"Plaka güncellendi: {item_name_element.text}")

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

            logging.info(f"Adres bilgileri güncellendi: {formatted_invoice_data['Adres']}, {formatted_invoice_data['Il']}, {formatted_invoice_data['Ilce']}")

        tree.write('ornek.xml', pretty_print=True, xml_declaration=True, encoding='UTF-8')
        logging.info("XML file updated successfully.")
    except Exception as e:
        logging.error(f"Error updating XML: {e}")

def main_loop():
    global processed_ka_numbers, current_token
    processed_ka_numbers = load_processed_ka_numbers()
    last_token_time = None
    current_token = None
    last_session_time = None
    current_session = None
    current_company = 1  # Başlangıçta 1 (Avis) ile başla
    
    while True:
        try:
            current_time = datetime.now()
            
            # Token kontrolü
            if last_token_time is None or (current_time - last_token_time).total_seconds() >= 240:
                current_token = get_token()
                last_token_time = current_time
            
            # Şirket kontrolü
            company_name = "Avis" if current_company == 1 else "Budget"
            invoice_data_list = get_invoice_data(current_company)
            
            if invoice_data_list:
                new_invoices = [
                    invoice for invoice in invoice_data_list 
                    if invoice.get('KANo') not in processed_ka_numbers
                ]
                
                if not new_invoices:
                    logging.info(f"ℹ️ {company_name}'te yeni fatura bulunamadı")
                else:
                    # EDM session kontrolü
                    if last_session_time is None or (current_time - last_session_time).total_seconds() >= 3600:
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

                        login_response = client.service.Login(**login_request)
                        current_session = login_response.SESSION_ID
                        last_session_time = current_time
                        logging.info("✅ EDM'den session alındı")
                    
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
                            logging.info(f"✅ EDM'ye yeni bir {company_name} faturası eklendi (KA No: {invoice_data['KANo']})")
                            
                            processed_ka_numbers.add(invoice_data['KANo'])
                            save_processed_ka_numbers()
                            
                        except Exception as e:
                            logging.error(f"Error processing invoice {invoice_data.get('KANo')}: {e}")
            
            # Şirket değiştir (1 -> 2 veya 2 -> 1)
            current_company = 2 if current_company == 1 else 1
            
            # Her iki şirket kontrolü arasında 1 dakika bekle
            time.sleep(60)
            
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            time.sleep(60)

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

def check_user(client, session_id, vkn):
    logging.info(f"Checking user with VKN: {vkn}")
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
        logging.info("Sending CheckUser request...")
        response = client.service.CheckUser(REQUEST_HEADER=request_header, USER=user)
        logging.info("CheckUser Response Details:")
        logging.info(f"Full Response: {response}")

        # Response boş dizi kontrolü
        if not response or (isinstance(response, list) and len(response) == 0):
            logging.info("Empty response, user is not in e-invoice system")
            return "EARSIVFATURA", None
        else:
            logging.info("User found in e-invoice system")
            # İlk ALIAS değerini al
            alias = response[0].get('ALIAS') if response and len(response) > 0 else None
            return "TICARIFATURA", alias

    except Exception as e:
        logging.error(f"Unexpected error in CheckUser: {e}")
        return "EARSIVFATURA", None

def update_xml_and_load(client, session_id, vkn, alias, vergi_dairesi, unvan, tam_adres, il, ilce):
    try:
        print("\n📝 XML güncelleniyor...")
        
        # XML dosyasını oku ve namespace'leri koru
        ET.register_namespace('cac', 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2')
        ET.register_namespace('cbc', 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2')
        ET.register_namespace('ext', 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2')
        ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        ET.register_namespace('xades', 'http://uri.etsi.org/01903/v1.3.2#')
        ET.register_namespace('udt', 'urn:un:unece:uncefact:data:specification:UnqualifiedDataTypesSchemaModule:2')
        ET.register_namespace('ubltr', 'urn:oasis:names:specification:ubl:schema:xsd:TurkishCustomizationExtensionComponents')
        ET.register_namespace('qdt', 'urn:oasis:names:specification:ubl:schema:xsd:QualifiedDatatypes-2')
        ET.register_namespace('ds', 'http://www.w3.org/2000/09/xmldsig#')
        
        tree = ET.parse('ornek.xml')
        root = tree.getroot()
        
        namespaces = {
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
        }

        # Güncel tarih ve saat
        current_date = datetime.now().strftime('%Y-%m-%d')
        current_time = datetime.now().strftime('%H:%M:%S')

        # Tüm IssueDate elementlerini güncelle
        for issue_date in root.findall('.//cbc:IssueDate', namespaces):
            issue_date.text = current_date
            print(f"✅ IssueDate güncellendi: {current_date}")

        # IssueTime elementini güncelle
        issue_time = root.find('.//cbc:IssueTime', namespaces)
        if issue_time is not None:
            issue_time.text = current_time
            print(f"✅ IssueTime güncellendi: {current_time}")

        # UUID ve ID güncelle
        uuid_element = root.find('.//cbc:UUID', namespaces)
        id_element = root.find('.//cbc:ID', namespaces)
        
        # Yeni UUID oluştur
        new_uuid = str(uuid.uuid4())
        
        # UUID güncelle
        if uuid_element is not None:
            uuid_element.text = new_uuid
            print(f"✅ UUID güncellendi: {new_uuid}")
        
       

        # AccountingCustomerParty güncellemeleri
        customer = root.find('.//cac:AccountingCustomerParty', namespaces)
        if customer is not None:
            # VKN güncelle
            vkn_element = customer.find('.//cac:PartyIdentification/cbc:ID[@schemeID="VKN"]', namespaces)
            if vkn_element is not None:
                vkn_element.text = vkn
            
            # Unvan güncelle
            name_element = customer.find('.//cac:PartyName/cbc:Name', namespaces)
            if name_element is not None:
                name_element.text = unvan if unvan else ""
            
            # Adres güncelle
            address_element = customer.find('.//cac:PostalAddress/cbc:BuildingName', namespaces)
            if address_element is not None:
                address_element.text = tam_adres
            
            # İlçe güncelle
            subdivision_element = customer.find('.//cac:PostalAddress/cbc:CitySubdivisionName', namespaces)
            if subdivision_element is not None:
                subdivision_element.text = ilce
            
            # İl güncelle
            city_element = customer.find('.//cac:PostalAddress/cbc:CityName', namespaces)
            if city_element is not None:
                city_element.text = il
            
            # Vergi dairesi güncelle
            tax_scheme_element = customer.find('.//cac:PartyTaxScheme/cac:TaxScheme/cbc:Name', namespaces)
            if tax_scheme_element is not None:
                tax_scheme_element.text = vergi_dairesi if vergi_dairesi else ""

        # XML'i kaydet (namespace'leri koruyarak)
        tree.write('ornek.xml', encoding='UTF-8', xml_declaration=True)
        print("✅ XML güncellendi")
        
        # LoadInvoice için XML'i oku
        with open('ornek.xml', 'rb') as xml_file:
            xml_content = xml_file.read()
            encoded_content = base64.b64encode(xml_content).decode('utf-8')

        # LoadInvoice request header
        request_header = {
            "SESSION_ID": session_id,
            "CLIENT_TXN_ID": str(uuid.uuid4()),
            "ACTION_DATE": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+03:00",
            "REASON": "E-fatura/E-Arşiv gönder-al testleri için",
            "APPLICATION_NAME": "EDM MINI CONNECTOR v1.0",
            "HOSTNAME": "MDORA17",
            "CHANNEL_NAME": "TEST",
            "COMPRESSED": "N"
        }

        # Sender bilgileri
        sender = {
            "vkn": "8930043435",
            "alias": "urn:mail:urartugb@edmbilisim.com"
        }

        # Receiver bilgileri - CheckUser'dan gelen tam alias kullanılıyor
        receiver = {
            "vkn": vkn,
            "alias": alias  # CheckUser'dan gelen tam alias değeri (örn: urn:mail:31193defaultpk@isnet.com)
        }

        print("\n📤 LoadInvoice Bilgileri:")
        print(f"Sender: {json.dumps(sender, indent=2)}")
        print(f"Receiver: {json.dumps(receiver, indent=2)}")

        # Invoice içeriği
        invoice = {
            "TRXID": "0",
            "HEADER": {
                "SENDER": sender["vkn"],
                "RECEIVER": receiver["vkn"],
                "FROM": sender["alias"],
                "TO": receiver["alias"],
                "INTERNETSALES": False,
                "EARCHIVE": False,
                "EARCHIVE_REPORT_SENDDATE": "0001-01-01",
                "CANCEL_EARCHIVE_REPORT_SENDDATE": "0001-01-01",
            },
            "CONTENT": encoded_content
        }

        try:
            print("\n📤 LoadInvoice isteği gönderiliyor...")
            print(f"Request Header: {json.dumps(request_header, indent=2)}")
            print(f"Sender: {json.dumps(sender, indent=2)}")
            print(f"Receiver: {json.dumps(receiver, indent=2)}")
            
            response = client.service.LoadInvoice(
                REQUEST_HEADER=request_header,
                SENDER=sender,
                RECEIVER=receiver,
                INVOICE=[invoice],
                GENERATEINVOICEIDONLOAD=True
            )
            
            print("\n📥 LoadInvoice yanıtı alındı:")
            serialized_response = serialize_object(response)
            
            # Date tipini string'e çevir
            if (response and 
                hasattr(response, 'INVOICE') and 
                response.INVOICE and 
                response.INVOICE[0].HEADER.STATUS == 'LOAD - SUCCEED'):
                print("\n✅ Fatura başarıyla yüklendi")
                return True
            else:
                error_msg = "Fatura yükleme başarısız"
                if hasattr(response, 'ERROR'):
                    error_msg += f": {response.ERROR}"
                print(f"\n❌ {error_msg}")
                return False

        except Exception as e:
            print(f"\n❌ LoadInvoice hatası: {str(e)}")
            traceback.print_exc()
            return False

    except Exception as e:
        print(f"\n❌ XML güncelleme hatası: {str(e)}")
        traceback.print_exc()
        return False

def get_otokoc_data():
    try:
        print("\n🔄 Otokoc API'den veriler alınıyor...")
        
        # Token al
        url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetToken"
        payload = {
            "Username": "UrartuTrz",
            "Password": "Tsv*57139!"
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            response_data = response.json()
            
            if 'Data' not in response_data or 'Token' not in response_data['Data']:
                print("❌ Token alınamadı: Geçersiz response format")
                return []
                
            token = response_data['Data']['Token']
            print("✅ Token başarıyla alındı")
            
            # Faturaları çek
            url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetInvoiceList"
            today = datetime.now().strftime("%Y%m%d")

            payload = {
                "Token": token,
                "LicenseNo": 1,
                "InvoiceDate": "",
                "StartDate": today,
                "EndDate": today
            }
            
            response = requests.post(url, json=payload)
            response.raise_for_status()
            response_data = response.json()
            
            if response_data.get('MessageEN') == "Token is expired":
                print("❌ Token süresi dolmuş")
                return []
                
            if 'Data' not in response_data or 'Invoices' not in response_data['Data']:
                print("❌ Faturalar alınamadı: Geçersiz response format")
                return []
            
            filtered_invoices = []
            today = datetime.now().date()
            cutoff_time = datetime.strptime("00:00:00", "%H:%M:%S").time()

            for invoice in response_data['Data']['Invoices']:
                try:
                    islem_saati = datetime.fromisoformat(invoice['IslemSaati'])
                    if islem_saati.date() == today and islem_saati.time() > cutoff_time:
                        filtered_invoices.append(invoice)
                except (KeyError, ValueError) as e:
                    print(f"⚠️ Fatura işlenirken hata: {str(e)}")
                    continue

            if filtered_invoices:
                print(f"✅ {len(filtered_invoices)} adet fatura başarıyla alındı")
            else:
                print("ℹ️ Filtreleme sonrası fatura bulunamadı")
                
            return filtered_invoices

        except requests.exceptions.RequestException as e:
            print(f"❌ API hatası: {str(e)}")
            return []
            
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {str(e)}")
        return []

def main():
    try:
        # EDM'ye bağlan
        client, session_id = edm_login()
        if not client or not session_id:
            print("❌ EDM bağlantısı başarısız!")
            return

        # Otokoc API'den verileri al
        invoices = get_otokoc_data()
        if not invoices:
            print("❌ İşlenecek fatura bulunamadı")
            return

        print(f"\n📋 Toplam {len(invoices)} fatura işlenecek")

        # Her fatura için işlem yap
        for index, invoice in enumerate(invoices, 1):
            vkn = invoice.get('VergiNumarasi')
            print(f"\n{'='*50}")
            print(f"🔄 Fatura {index}/{len(invoices)} işleniyor")
            print(f"📝 VKN: {vkn}")
            print(f"{'='*50}")

            if not vkn:
                print("❌ VKN bulunamadı, fatura atlanıyor")
                continue

            # Firma bilgilerini kontrol et
            alias, vergi_dairesi, unvan, tam_adres, il, ilce = check_user_and_get_info(client, session_id, vkn)
            
            if not alias:
                print(f"\n❌ VKN: {vkn} - Firma e-fatura mükellefi değil veya bilgiler alınamadı")
                continue

            print("\n📋 Firma Bilgileri:")
            print(f"Unvan: {unvan}")
            print(f"VKN: {vkn}")
            print(f"Alias: {alias}")
            print(f"Vergi Dairesi: {vergi_dairesi}")
            print(f"Adres: {tam_adres}")
            print(f"İl: {il}")
            print(f"İlçe: {ilce}")

            # XML güncelle ve faturayı yükle
            if update_xml_and_load(client, session_id, vkn, alias, vergi_dairesi, unvan, tam_adres, il, ilce):
                print(f"\n✅ VKN: {vkn} - İşlem başarıyla tamamlandı")
            else:
                print(f"\n❌ VKN: {vkn} - İşlem başarısız")

            # İşlemler arası kısa bekle
            time.sleep(1)

        print("\n✅ Tüm faturalar işlendi")

    except Exception as e:
        print(f"\n❌ Genel hata: {str(e)}")
        traceback.print_exc()

def load_invoice(receiver_data):
    logging.info("Loading invoice...")
    logging.info(f"Receiver data: {receiver_data}")

    try:
        # WSDL URL ve Client oluşturma
        wsdl_url = "https://portal2.edmbilisim.com.tr/EFaturaEDM/EFaturaEDM.svc?wsdl"
        client = Client(wsdl=wsdl_url)
        action_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-1] + "+03:00"

        # XML dosyasını kontrol et
        tree = ET.parse('ornek.xml')
        root = tree.getroot()
        namespaces = {
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
        }
        
        # ProfileID'yi kontrol et (EARSIVFATURA mı TICARIFATURA mı?)
        profile_id = root.find(".//cbc:ProfileID", namespaces)
        is_earchive = profile_id is not None and profile_id.text == "EARSIVFATURA"
        logging.info(f"Fatura tipi: {'EARSIVFATURA' if is_earchive else 'TICARIFATURA'}")

        # XML'deki VKN'yi kontrol et
        xml_vkn_element = root.find(".//cac:AccountingCustomerParty//cac:PartyIdentification/cbc:ID", namespaces)
        if xml_vkn_element is not None:
            xml_vkn = xml_vkn_element.text
            logging.info(f"XML'deki VKN: {xml_vkn}")
            logging.info(f"Gönderilecek VKN: {receiver_data['vkn']}")
            
            # VKN'ler uyuşmuyorsa güncelle
            if xml_vkn != receiver_data['vkn']:
                logging.warning(f"VKN uyuşmazlığı tespit edildi. XML: {xml_vkn}, Receiver: {receiver_data['vkn']}")
                xml_vkn_element.text = receiver_data['vkn']
                tree.write('ornek.xml', encoding='UTF-8', xml_declaration=True)
                logging.info("XML'deki VKN güncellendi")

        # Login işlemi
        login_request_header = {
            "SESSION_ID": str(uuid.uuid4()),
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
            "USER_NAME": "otomasyon",
            "PASSWORD": "123456789"
        }

        logging.info("Logging in to EDM...")
        login_response = client.service.Login(**login_request)
        session_id = login_response.SESSION_ID
        logging.info(f"Login successful. Session ID: {session_id}")

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

        sender = {
            "vkn": "8930043435",
            "alias": "urn:mail:urartugb@edmbilisim.com"
        }

        # E-Arşiv fatura için alıcı bilgilerini düzenle
        if is_earchive:
            receiver_data = {
                "vkn": receiver_data['vkn'],
                "alias": f"urn:mail:defaultpk@edmbilisim.com.tr"  # E-Arşiv için sabit alias
            }

        # XML içeriğini oku ve encode et
        with open('ornek.xml', 'rb') as xml_file:
            xml_content = xml_file.read()
            encoded_content = base64.b64encode(xml_content).decode('utf-8')

        invoice = {
            "TRXID": "0",
            "HEADER": {
                "SENDER": sender["vkn"],
                "RECEIVER": receiver_data['vkn'],
                "FROM": sender["alias"],
                "TO": receiver_data['alias'],
                "INTERNETSALES": False,
                "EARCHIVE": is_earchive,
                "EARCHIVE_REPORT_SENDDATE": "0001-01-01",
                "CANCEL_EARCHIVE_REPORT_SENDDATE": "0001-01-01",
            },
            "CONTENT": encoded_content
        }

        logging.info("Sending LoadInvoice request...")
        logging.info(f"Request details: Sender={sender}, Receiver={receiver_data}")
        logging.info(f"Invoice HEADER: {invoice['HEADER']}")

        response = client.service.LoadInvoice(
            REQUEST_HEADER=request_header,
            SENDER=sender,
            RECEIVER=receiver_data,
            INVOICE=[invoice],
            GENERATEINVOICEIDONLOAD=True
        )
        
        serialized_response = serialize_object(response)
        logging.info(f"LoadInvoice response: {serialized_response}")

        if (response and 
            hasattr(response, 'INVOICE') and 
            response.INVOICE and 
            response.INVOICE[0].HEADER.STATUS == 'LOAD - SUCCEED'):
            logging.info("Invoice loaded successfully")
            return True
        else:
            error_msg = "Invoice loading failed"
            if hasattr(response, 'ERROR'):
                error_msg += f": {response.ERROR}"
            logging.error(error_msg)
            return False

    except Exception as e:
        logging.error(f"Error occurred while loading invoice: {str(e)}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    logging.info("Starting continuous invoice processing...")
    main_loop()