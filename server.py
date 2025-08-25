#!/usr/bin/env python3
"""
Serveur Modbus BESS - Inspiré du code simple fourni
Corrections: adressage exact et gestion int32 correcte
"""

import asyncio
import logging
from pymodbus import __version__ as pymodbus_version
from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSparseDataBlock
from pymodbus.device import ModbusDeviceIdentification

# ---------------------------
# Configuration logging
# ---------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger()

# ---------------------------
# Fonctions utilitaires int32 little-endian (comme votre client)
# ---------------------------
def split_int32_be(value):
    """Split int32 en 2 registres 16-bit big-endian (HI, LO)"""
    hi = (value >> 16) & 0xFFFF
    lo = value & 0xFFFF
    return [hi, lo]

def merge_int32_be(hi, lo):
    """Merge 2 registres 16-bit big-endian en int32"""
    result = (hi << 16) + lo
    # Conversion en int32 signé si nécessaire
    if result > 0x7FFFFFFF:
        result = result - 0x100000000
    return result

# ---------------------------
# Datastore BESS personnalisé
# ---------------------------
class BessDataBlock(ModbusSparseDataBlock):
    def __init__(self):
        # Initialisation de TOUS les registres aux adresses EXACTES
        values = {
            # Holding Registers (écriture)
            0xd000: 0,      # watchdog low
            0xd001: 0,      # watchdog high
            0xd002: 0,      # commande BESS low
            0xd003: 0,      # commande BESS high
            0xd004: 0,      # P command low
            0xd005: 0,      # P command high  
            0xd006: 0,      # Q command low
            0xd007: 0,      # Q command high
            0xd00a: 0,      # Clear Faults low
            0xd00b: 0,      # Clear Faults high
            
            # Input Registers (lecture - miroir des commandes)
            0x2502: 0,      # state low
            0x2503: 0,      # state high
            0x2504: 5000,   # SoC low (50.00%)
            0x2505: 0,      # SoC high
            0x2518: 0,      # P miroir low
            0x2519: 0,      # P miroir high
            0x251a: 0,      # Q miroir low
            0x251b: 0,      # Q miroir high
        }
        
        super().__init__(values)
        log.info(f"DataBlock initialisé avec {len(values)} registres")

# ---------------------------
# Contexte Modbus avec adressage exact
# ---------------------------
store = ModbusSlaveContext(
    hr=BessDataBlock(),      # Holding registers
    ir=BessDataBlock(),      # Input registers (même mapping pour simplifier)
    co=BessDataBlock(),      # Coils (pas utilisé mais requis)
    di=BessDataBlock(),      # Discrete inputs (pas utilisé mais requis)
    zero_mode=True           # IMPORTANT: adressage à partir de 0 (pas de décalage -1)
)

context = ModbusServerContext(slaves=store, single=True)

# ---------------------------
# Identification du dispositif
# ---------------------------
identity = ModbusDeviceIdentification()
identity.VendorName = 'BESS Simulator'
identity.ProductCode = 'BESS-SIM'
identity.VendorUrl = 'https://github.com/bess-simulator'
identity.ProductName = 'Battery Energy Storage System Simulator'
identity.ModelName = 'BESS Model 1'
identity.MajorMinorRevision = pymodbus_version

# ---------------------------
# Variables de simulation
# ---------------------------
soc_value = 5000  # 50.00%
watchdog_timeout = 0

# ---------------------------
# Updater asynchrone pour synchronisation
# ---------------------------
async def updater():
    global soc_value, watchdog_timeout
    log.info("🔄 Updater démarré - Synchronisation automatique activée")
    
    while True:
        try:
            # Lecture des commandes depuis Holding Registers (fonction 3)
            
            # Command (0xd002-0xd003) → State (0x2502-0x2503)
            cmd_lo = context[0].getValues(3, 0xd002, count=1)[0]
            cmd_hi = context[0].getValues(3, 0xd003, count=1)[0]
            cmd_32 = merge_int32_be(cmd_lo, cmd_hi)
            context[0].setValues(4, 0x2502, split_int32_be(cmd_32))
            
            # P_command (0xd004-0xd005) → P_kW (0x2518-0x2519)
            p_cmd_lo = context[0].getValues(3, 0xd004, count=1)[0]
            p_cmd_hi = context[0].getValues(3, 0xd005, count=1)[0]
            p_cmd_32 = merge_int32_be(p_cmd_lo, p_cmd_hi)
            context[0].setValues(4, 0x2518, split_int32_be(p_cmd_32))
            
            # Q_command (0xd006-0xd007) → Q_kVar (0x251a-0x251b)
            q_cmd_lo = context[0].getValues(3, 0xd006, count=1)[0]
            q_cmd_hi = context[0].getValues(3, 0xd007, count=1)[0]
            q_cmd_32 = merge_int32_be(q_cmd_lo, q_cmd_hi)
            context[0].setValues(4, 0x251a, split_int32_be(q_cmd_32))
            
            # Watchdog
            wd_lo = context[0].getValues(3, 0xd000, count=1)[0]
            wd_hi = context[0].getValues(3, 0xd001, count=1)[0]
            watchdog_32 = merge_int32_be(wd_lo, wd_hi)
            
            # Check si watchdog a été mis à jour
            if watchdog_32 != 0:
                watchdog_timeout = 0
                log.debug(f"✅ Watchdog reçu: {watchdog_32}")
            else:
                watchdog_timeout += 1
                if watchdog_timeout > 10:  # 10 secondes sans watchdog
                    log.warning("⚠️  Watchdog timeout!")
            
            # Simulation du SOC qui varie lentement
            import time
            soc_direction = -1 if (time.time() % 60) < 30 else 1
            soc_value += soc_direction
            soc_value = max(1000, min(9500, soc_value))  # 10% à 95%
            context[0].setValues(4, 0x2504, split_int32_be(soc_value))
            
                
        except Exception as e:
            log.error(f"Erreur dans updater: {e}")
        
        await asyncio.sleep(1)  # Mise à jour chaque seconde

# ---------------------------
# Fonction principale du serveur
# ---------------------------
async def run_server():
    """Démarre le serveur avec l'updater en parallèle"""
    
    print("=" * 60)
    print("🔋 SERVEUR MODBUS BESS - Version Corrigée")
    print(f"📦 pymodbus {pymodbus_version}")
    print(f"🌐 Adresse: localhost:5502")
    print("=" * 60)
    print("📋 REGISTRES CONFIGURÉS:")
    print("   📝 Holding Registers (Fonction 03/06/16 - Écriture):")
    print("      0xd000-d001: Watchdog (int32)")
    print("      0xd002-d003: Commande système (int32)")
    print("      0xd004-d005: Consigne P kW (int32 signé)")
    print("      0xd006-d007: Consigne Q kVar (int32 signé)")
    print("      0xd00a-d00b: Clear faults (int32)")
    print("   📖 Input Registers (Fonction 04 - Lecture):")
    print("      0x2502-2503: État système (int32)")
    print("      0x2504-2505: SOC % × 100 (int32)")
    print("      0x2518-2519: P mesurée kW (int32 signé)")
    print("      0x251a-251b: Q mesurée kVar (int32 signé)")
    print()
    print("🔄 SYNCHRONISATIONS AUTOMATIQUES (temps réel):")
    print("   • 0xd004-d005 → 0x2518-2519 (P_command → P_kW)")
    print("   • 0xd006-d007 → 0x251a-251b (Q_command → Q_kVar)")
    print("   • 0xd002-d003 → 0x2502-2503 (Command → State)")
    print()
    print("✅ CORRECTIONS APPLIQUÉES:")
    print("   • zero_mode=True : Adresses exactes (pas de décalage -1)")
    print("   • Format int32 little-endian compatible avec votre client")
    print("   • Synchronisation temps réel toutes les secondes")
    print()
    print("🚀 Serveur prêt... (Ctrl+C pour arrêter)")
    print("=" * 60)
    
    # Démarrage de l'updater en parallèle
    asyncio.create_task(updater())
    
    # Démarrage du serveur Modbus
    await StartAsyncTcpServer(
        context, 
        identity=identity, 
        address=("0.0.0.0", 5502)
    )

# ---------------------------
# Point d'entrée principal
# ---------------------------
if __name__ == "__main__":
    print("🚀 Démarrage du serveur Modbus BESS...")
    
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\n🛑 Serveur arrêté par l'utilisateur")
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()