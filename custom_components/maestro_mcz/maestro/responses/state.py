from dataclasses import dataclass, field
import logging



_LOGGER = logging.getLogger(__name__)

@dataclass
class State:
    vel_imp_ventola_fumi: int | None = None
    vel_real_ventola_fumi: int | None = None
    vel_imp_coclea: int | None = None
    vel_real_coclea: int | None = None
    pressione: int | None = None
    pressione_imp: int | None = None
    temp_scheda: float | None = None
    index_vel_v1: int | None = None
    index_vel_v2: int | None = None
    index_vel_v3: int | None = None
    potenza_att: int | None = None
    potenza_counter: int | None = None
    t_dur_pul: int | None = None
    t_int_pul: int | None = None
    state: str | None = None
    state_duration: int | None = None
    temp_fumi: int | None = None
    mode: str | None = None
    crono_enabled: bool | None = None
    att_eco: bool | None = None
    pul_brac: bool | None = None
    ingr_amb: int | None = None
    sens_liv_pellet: bool | None = None
    nome_banca_dati_sel: str | None = None
    adaptive_on: bool | None = None
    last_alarm: str | None = None
    set_amb1: float | None = None
    temp_amb_install: float | None = None
    status_timestamp: int | None = None
    last_stdt: int | None = None
    site_time_zone: str | None = None
    blocking_event_id: str | None = None
    description: str | None = None
    is_connected: bool | None = None
    is_in_error: bool | None = None
    
    #hydro stove fields
    power_caller: object | None = None
    pompa: int | None = None
    est_inv: int | None = None
    conf_imp: int | None = None
    stato_valv: bool | None = None
    temp_caldaia: float | None = None
    set_cald: float | None = None
    ist_neg_cald: float | None = None
    ist_pos_cald: float | None = None
    temp_bollitore: float | None = None
    set_boiler: float | None = None
    ist_neg_boiler: float | None = None
    ist_pos_boiler: float | None = None
    temp_puffer: float | None = None
    set_puffer: float | None = None
    ist_neg_puffer: float | None = None
    ist_pos_puffer: float | None = None
    set_san: float | None = None
    temp_NTC1: float | None = None
    temp_NTC2: float | None = None
    temp_NTC3: float | None = None
    ing_term_amb1: bool | None = None
    ing_term_amb2: bool | None = None
    ing_term_amb3: bool | None = None
    ingr_ntc2: int | None = None
    ingr_ntc3: int | None = None
    

    unknown_fields: dict | None = None

    def __init__(self, json) -> None:
         if(json is not None and len(json) > 0):
            temp_unknown_fields = {}
            for key in json:
                match key:
                    case "vel_imp_ventola_fumi": self.vel_imp_ventola_fumi = json[key]
                    case "vel_real_ventola_fumi": self.vel_real_ventola_fumi = json[key]
                    case "vel_imp_coclea": self.vel_imp_coclea = json[key]
                    case "vel_real_coclea": self.vel_real_coclea = json[key]
                    case "pressione": self.pressione = json[key]
                    case "pressione_imp": self.pressione_imp = json[key]
                    case "temp_scheda": self.temp_scheda = json[key]
                    case "index_vel_v1": self.index_vel_v1 = json[key]
                    case "index_vel_v2": self.index_vel_v2 = json[key]
                    case "index_vel_v3": self.index_vel_v3 = json[key]
                    case "potenza_att": self.potenza_att = json[key]
                    case "potenza_counter": self.potenza_counter = json[key]
                    case "t_dur_pul": self.t_dur_pul = json[key]
                    case "t_int_pul": self.t_int_pul = json[key]
                    case "state": self.state = json[key]
                    case "state_duration": self.state_duration = json[key]
                    case "temp_fumi": self.temp_fumi = json[key]
                    case "mod_lav_att": self.mode = json[key]
                    case "crono_enabled": self.crono_enabled = json[key]
                    case "att_eco": self.att_eco = json[key]
                    case "pul_brac": self.pul_brac = json[key]
                    case "ingr_amb": self.ingr_amb = json[key]
                    case "sens_liv_pellet": self.sens_liv_pellet = json[key]
                    case "nome_banca_dati_sel": self.nome_banca_dati_sel = json[key]
                    case "adaptive_on": self.adaptive_on = json[key]
                    case "last_alarm": self.last_alarm = json[key]
                    case "set_amb1": self.set_amb1 = json[key]
                    case "temp_amb_install": self.temp_amb_install = json[key]
                    case "StatusTimestamp": self.status_timestamp = json[key]
                    case "LastSTDT": self.last_stdt = json[key]
                    case "SiteTimeZone": self.site_time_zone = json[key]
                    case "BlockingEventId": self.blocking_event_id = json[key]
                    case "Description": self.description = json[key]
                    case "IsConnected": self.is_connected = json[key]
                    case "IsInError": self.is_in_error = json[key]
                    case "power_caller": self.power_caller = json[key]
                    case "pompa": self.pompa = json[key]
                    case "est_inv": self.est_inv = json[key]
                    case "conf_imp": self.conf_imp = json[key]
                    case "stato_valv": self.stato_valv = json[key]
                    case "temp_caldaia": self.temp_caldaia = json[key]
                    case "set_cald": self.set_cald = json[key]
                    case "ist_neg_cald": self.ist_neg_cald = json[key]
                    case "ist_pos_cald": self.ist_pos_cald = json[key]
                    case "temp_bollitore": self.temp_bollitore = json[key]
                    case "set_boiler": self.set_boiler = json[key]
                    case "ist_neg_boiler": self.ist_neg_boiler = json[key]
                    case "ist_pos_boiler": self.ist_pos_boiler = json[key]
                    case "temp_puffer": self.temp_puffer = json[key]
                    case "set_puffer": self.set_puffer = json[key]
                    case "ist_neg_puffer": self.ist_neg_puffer = json[key]
                    case "ist_pos_puffer": self.ist_pos_puffer = json[key]
                    case "set_san": self.set_san = json[key]
                    case "temp_NTC1": self.temp_NTC1 = json[key]
                    case "temp_NTC2": self.temp_NTC2 = json[key]
                    case "temp_NTC3": self.temp_NTC3 = json[key]
                    case "ing_term_amb1": self.ing_term_amb1 = json[key]
                    case "ing_term_amb2": self.ing_term_amb2 = json[key]
                    case "ing_term_amb3": self.ing_term_amb3 = json[key]
                    case "ingr_ntc2": self.ingr_ntc2 = json[key]
                    case "ingr_ntc3": self.ingr_ntc3 = json[key]
                    case _ :
                        temp_unknown_fields[key] = json[key]
                        _LOGGER.warning(f"Unknown state property '{key}' received from API endpoint. If this happens, please make an issue on the github repository")
            if temp_unknown_fields:
                self.unknown_fields = temp_unknown_fields
