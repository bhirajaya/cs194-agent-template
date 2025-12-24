"""
Game Logger - Saves action logs to JSON file
Tracks all player actions per round for analysis
"""
import json
import os
from datetime import datetime
from typing import Dict, List

class GameLogger:
    """Logs game actions to JSON file"""
    
    def __init__(self, log_file: str = "game_log.json"):
        self.log_file = log_file
        self.logs = {
            'game_start_time': None,
            'rounds': []
        }
    
    def clear_log(self):
        """Clear the log file and start fresh"""
        self.logs = {
            'game_start_time': datetime.now().isoformat(),
            'game_info': {},
            'rounds': []
        }
        self._save_to_file()
        print(f"📋 Game log cleared: {self.log_file}")
    
    def set_game_info(self, challenge: str, num_players: int):
        """Set initial game information"""
        self.logs['game_info'] = {
            'challenge': challenge,
            'num_players': num_players,
            'start_time': datetime.now().isoformat()
        }
        self._save_to_file()
    
    def log_round(self, round_number: int, player_actions: List[Dict]):
        """
        Log all actions from a round
        
        Args:
            round_number: Current round number
            player_actions: List of {player_id, action, result} dicts
        """
        round_data = {
            'round_number': round_number,
            'timestamp': datetime.now().isoformat(),
            'actions': []
        }
        
        for action_data in player_actions:
            player_id = action_data.get('player_id')
            action_type = action_data.get('action')
            result = action_data.get('result', {})
            
            # Format action log entry
            log_entry = {
                'player_id': player_id,
                'action': action_type,
                'success': result.get('success', False),
                'energy_before': action_data.get('energy_before'),
                'energy_after': result.get('energy'),
                'details': self._extract_relevant_details(action_type, result)
            }
            
            round_data['actions'].append(log_entry)
        
        # Add round to logs
        self.logs['rounds'].append(round_data)
        
        # Save to file
        self._save_to_file()
        
        print(f"📋 Round {round_number} logged: {len(player_actions)} actions")
    
    def _extract_relevant_details(self, action_type: str, result: Dict) -> Dict:
        """Extract relevant details based on action type"""
        details = {}
        
        if action_type == 'move':
            details['new_position'] = result.get('position')
            details['message'] = result.get('message')
        
        elif action_type == 'attack_player':
            details['damage_dealt'] = result.get('damage_dealt')
            details['energy_stolen'] = result.get('energy_stolen')
            details['target_health'] = result.get('target_health')
            details['eliminated'] = result.get('eliminated', False)
        
        elif action_type == 'solve_ctf':
            details['flag_valid'] = result.get('flag_valid', False)
            details['ctf_progress'] = result.get('ctf_progress')
            details['hints_unlocked'] = result.get('hints_unlocked', [])
            if result.get('game_over'):
                details['winner'] = True
        
        elif action_type == 'claim_territory':
            details['position'] = result.get('position')
            details['total_territories'] = result.get('territories')
            details['income'] = result.get('income')
        
        elif action_type == 'rest':
            details['health'] = result.get('health')
            details['shield'] = result.get('shield')
        
        elif action_type == 'scout':
            details['players_found'] = len(result.get('intel', {}).get('visible_players', []))
        
        elif action_type == 'fortify':
            details['defense'] = result.get('defense')
            details['shield'] = result.get('shield')
        
        elif action_type == 'steal_progress':
            details['progress_stolen'] = result.get('progress_stolen')
            details['hints_stolen'] = result.get('hints_stolen', [])
            details['attacker_progress'] = result.get('attacker_progress')
        
        # Include error messages
        if 'error' in result:
            details['error'] = result['error']
        
        if 'message' in result and action_type != 'move':
            details['message'] = result['message']
        
        return details
    
    def log_game_end(self, winner: int, final_state: Dict):
        """Log game end information"""
        self.logs['game_end'] = {
            'timestamp': datetime.now().isoformat(),
            'winner': winner,
            'total_rounds': len(self.logs['rounds']),
            'final_standings': self._get_final_standings(final_state)
        }
        self._save_to_file()
        print(f"📋 Game ended - Winner: Player {winner}")
    
    def _get_final_standings(self, game_state: Dict) -> List[Dict]:
        """Get final player standings"""
        standings = []
        for player_id, player in game_state.get('players', {}).items():
            standings.append({
                'player_id': int(player_id),
                'status': player.get('status'),
                'ctf_progress': player.get('ctf_progress'),
                'kills': player.get('kills'),
                'territories': player.get('territories'),
                'final_health': player.get('health'),
                'final_energy': player.get('energy')
            })
        
        # Sort by status (winner first) then by CTF progress
        standings.sort(key=lambda x: (
            0 if x['status'] == 'winner' else (1 if x['status'] == 'alive' else 2),
            -x['ctf_progress']
        ))
        
        return standings
    
    def _save_to_file(self):
        """Save logs to JSON file"""
        try:
            with open(self.log_file, 'w') as f:
                json.dump(self.logs, f, indent=2)
        except Exception as e:
            print(f"Error saving log file: {e}")
    
    def get_round_summary(self, round_number: int) -> Dict:
        """Get summary of a specific round"""
        for round_data in self.logs['rounds']:
            if round_data['round_number'] == round_number:
                return round_data
        return None
    
    def get_player_history(self, player_id: int) -> List[Dict]:
        """Get all actions taken by a specific player"""
        player_actions = []
        for round_data in self.logs['rounds']:
            for action in round_data['actions']:
                if action['player_id'] == player_id:
                    player_actions.append({
                        'round': round_data['round_number'],
                        **action
                    })
        return player_actions

# Global logger instance
game_logger = GameLogger()

