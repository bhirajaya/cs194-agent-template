"""
CTF Hunger Games - Battle Royale on Hexagonal Board
Integrates CTF benchmark challenges into a competitive multi-agent environment
"""
import time
import random
import json
from typing import Dict, List, Optional, Tuple
from enum import Enum
from openai import OpenAI, OpenAIError
from config import Config

class ActionType(Enum):
    MOVE = "move"
    ATTACK_PLAYER = "attack_player"
    SOLVE_CTF = "solve_ctf"
    CLAIM_TERRITORY = "claim_territory"
    REST = "rest"
    SCOUT = "scout"
    DEFEND = "defend"
    STEAL_PROGRESS = "steal_progress"

class PlayerStatus(Enum):
    ALIVE = "alive"
    ELIMINATED = "eliminated"
    WINNER = "winner"
    LOST_TIMEOUT = "lost_timeout"  # Lost by timeout tiebreak (graceful loss)

class HexType(Enum):
    NORMAL = "normal"
    RESOURCE = "resource"  # Gives energy bonus (one-time only)

class CTFHungerGame:
    """
    Manages the CTF Hunger Games competition with 6 AI agents
    on a hexagonal board with strategic gameplay
    """
    
    def __init__(self, ctf_challenge: str):
        self.ctf_challenge = ctf_challenge
        self.board_radius = 4
        self.hexagons = self._initialize_board()
        self.players = self._initialize_players()
        self.green_agent = GreenAgent(self)
        self.round_number = 0
        self.turn_number = 0
        self.max_rounds = 20
        self.max_time = 300  # 5 minutes
        self.start_time = None
        self.game_over = False
        self.winner = None
        self.action_history = []
        
        # CTF hints unlock at progress milestones
        self.ctf_hints = [
            "The flag format is: flag{...}",
            "Look for patterns in the challenge description",
            "Try common CTF techniques: base64, rot13, XOR"
        ]
        
        # Initialize player vision after players are set
        for player_id in self.players:
            self._update_vision(player_id)
        
    def _initialize_board(self) -> Dict:
        """Initialize hexagonal board with axial coordinates"""
        hexagons = {}
        radius = self.board_radius
        
        # Fixed spawn positions (6 vertices)
        spawn_positions = [
            (0, -4),      # Top
            (4, -4),      # Top-right
            (4, 0),       # Bottom-right
            (0, 4),       # Bottom
            (-4, 4),      # Bottom-left
            (-4, 0)       # Top-left
        ]
        
        for q in range(-radius, radius + 1):
            for r in range(-radius, radius + 1):
                s = -q - r
                if abs(s) <= radius:
                    # Force spawn positions to be NORMAL (never obstacles)
                    if (q, r) in spawn_positions:
                        hex_type = HexType.NORMAL
                    else:
                        # Randomly assign special hexagon types
                        hex_type = self._get_random_hex_type()
                    
                    hexagons[(q, r)] = {
                        'type': hex_type,
                        'owner': None,
                        'defense': 0,
                        'bonus_consumed': False  # Track if resource bonus was taken
                    }
        
        return hexagons
    
    def _get_random_hex_type(self) -> HexType:
        """Randomly assign hexagon types - simplified (no obstacles/power)"""
        rand = random.random()
        if rand < 0.85:
            return HexType.NORMAL    # 85% normal terrain
        else:
            return HexType.RESOURCE  # 15% resource hexes
        
    def _initialize_players(self) -> Dict:
        """Initialize 6 players at the 6 vertices of the hexagonal board"""
        # Starting positions at the 6 vertices
        starting_positions = [
            (0, -4),      # Top
            (4, -4),      # Top-right
            (4, 0),       # Bottom-right
            (0, 4),       # Bottom
            (-4, 4),      # Bottom-left
            (-4, 0)       # Top-left
        ]
        
        players = {}
        for i in range(1, 7):
            players[i] = {
                'id': i,
                'name': f'Player {i}',
                'position': starting_positions[i-1],
                'energy': 15,
                'max_energy': 15,
                'health': 100,
                'shield': 0,
                'status': PlayerStatus.ALIVE,
                
                # CTF Progress
                'ctf_progress': 0,
                'ctf_hints': [],
                'ctf_attempts': 0,
                
                # Territory & Resources
                'territories': [],
                'territory_income': 0,
                
                # Combat
                'attack_power': 5,
                'defense_power': 3,
                'kills': 0,
                'defending': False,  # Blocks attacks for one round
                
                # Vision
                'vision_range': 2,
                'visible_hexagons': [],
                'visible_players': [],
                
                # Stats
                'actions_taken': 0,
                'idle_streak': 0,  # Track consecutive non-objective actions
                'last_actions': [],  # Track recent action history
                'since_objective': 0,  # Turns since last objective action
                'seen_tiles': set(),  # Tiles explored (for scout)
                'color': self._get_player_color(i)
            }
        
        return players
    
    def _get_player_color(self, player_id: int) -> str:
        colors = {1: 'red', 2: 'blue', 3: 'green', 4: 'yellow', 5: 'orange', 6: 'purple'}
        return colors.get(player_id, 'default')
    
    # Spawn validation no longer needed - no obstacles exist!
    
    # ========================================================================
    # HEXAGON COORDINATE HELPERS
    # ========================================================================
    
    def _is_adjacent(self, hex1: Tuple[int, int], hex2: Tuple[int, int]) -> bool:
        """Check if two hexagons are adjacent in axial coordinates"""
        q1, r1 = hex1
        q2, r2 = hex2
        dq = abs(q1 - q2)
        dr = abs(r1 - r2)
        ds = abs((q1 + r1) - (q2 + r2))
        return (dq + dr + ds) // 2 == 1
    
    def _hex_distance(self, hex1: Tuple[int, int], hex2: Tuple[int, int]) -> int:
        """Calculate distance between two hexagons"""
        q1, r1 = hex1
        q2, r2 = hex2
        return (abs(q1 - q2) + abs(r1 - r2) + abs((q1 + r1) - (q2 + r2))) // 2
    
    def _get_adjacent_hexagons(self, hex_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Get all adjacent hexagons"""
        q, r = hex_pos
        directions = [(1,0), (1,-1), (0,-1), (-1,0), (-1,1), (0,1)]
        adjacent = []
        for dq, dr in directions:
            neighbor = (q + dq, r + dr)
            if neighbor in self.hexagons:
                adjacent.append(neighbor)
        return adjacent
    
    def _find_nearest_unowned_for_player(self, player_id: int) -> Optional[Tuple[int, int]]:
        """Find nearest unowned hex for auto-move (engine-side safety valve)"""
        from collections import deque
        
        player = self.players[player_id]
        start = player['position']
        
        seen = {start}
        parent = {start: None}
        queue = deque([start])
        
        while queue:
            cur = queue.popleft()
            
            # Found unowned hex (not our starting position)
            if (cur != start 
                and cur in self.hexagons 
                and self.hexagons[cur]['owner'] is None):
                # Backtrack to find first step
                while parent[cur] != start:
                    cur = parent[cur]
                return list(cur)
            
            # Explore neighbors (all hexes are passable now)
            for neighbor in self._get_adjacent_hexagons(cur):
                if neighbor not in seen:
                    seen.add(neighbor)
                    parent[neighbor] = cur
                    queue.append(neighbor)
        
        return None
    
    def _update_vision(self, player_id: int):
        """Update what hexagons and players are visible to a player"""
        player = self.players[player_id]
        pos = player['position']
        vision = player['vision_range']
        
        # Get all hexagons within vision range
        visible_hexes = []
        for hex_coord in self.hexagons:
            if self._hex_distance(pos, hex_coord) <= vision:
                visible_hexes.append(hex_coord)
        
        player['visible_hexagons'] = visible_hexes
        
        # Get all alive players within visible hexagons
        visible_players = []
        for pid, p in self.players.items():
            if pid != player_id and p['status'] == PlayerStatus.ALIVE and p['position'] in visible_hexes:
                visible_players.append(pid)
        
        player['visible_players'] = visible_players
    
    def _apply_storm(self):
        """Apply storm pressure to discourage camping at edges"""
        # Safe radius shrinks every 5 rounds
        safe_radius = max(1, self.board_radius - (self.round_number // 5))
        center = (0, 0)
        for pid, p in self.players.items():
            if p['status'] != PlayerStatus.ALIVE:
                continue
            if self._hex_distance(center, p['position']) > safe_radius:
                # Soft penalty: pushes campers inward
                p['energy'] -= 2
                p['health'] -= 5
                print(f"⚠️ Storm hits Player {pid}: -2 energy, -5 health")
    
    def _apply_idle_tax(self, player_id: int, is_objective_action: bool):
        """Apply idle tax to discourage pure camping"""
        player = self.players[player_id]
        
        if is_objective_action:
            player['idle_streak'] = 0
        else:
            player['idle_streak'] += 1
            if player['idle_streak'] >= 3:
                player['energy'] -= 2
                print(f"💤 Idle tax on Player {player_id}: -2 energy")
                player['idle_streak'] = 0
    
    # ========================================================================
    # GAME CONTROL
    # ========================================================================
    
    def start_game(self):
        """Start the game"""
        self.start_time = time.time()
        self.game_over = False
        print(f"🎮 CTF Hunger Games Started!")
        print(f"Challenge: {self.ctf_challenge}")
        print(f"Players: 6 AI agents on hexagonal battlefield")
        
    def execute_turn(self, player_id: int, action: ActionType, data: Optional[Dict] = None):
        """Execute one turn for a player"""
        if self.game_over:
            return {'error': 'Game is over', 'winner': self.winner}
        
        player = self.players.get(player_id)
        if not player or player['status'] != PlayerStatus.ALIVE:
            return {'error': 'Player is not active'}
        
        # Check time limit
        if self.start_time and time.time() - self.start_time > self.max_time:
            return self.green_agent.timeout_elimination(player_id)
        
        # GREEN AGENT PRE-VALIDATION
        validation = self.green_agent.validate_action(player_id, action, data or {})
        
        if not validation['legal']:
            # BLOCK ILLEGAL MOVE
            return {
                'error': 'Illegal move blocked by Green Agent',
                'success': False,
                'validation': validation,
                'action': action.value
            }
        
        # Execute action
        result = self._execute_action(player_id, action, data)
        result['validation'] = validation  # Include validation in result
        
        # Apply idle tax (objective actions: SOLVE_CTF, ATTACK_PLAYER, STEAL_PROGRESS)
        is_objective = action in [ActionType.SOLVE_CTF, ActionType.ATTACK_PLAYER, ActionType.STEAL_PROGRESS]
        self._apply_idle_tax(player_id, is_objective)
        
        # Record action (use executed action, which may differ due to auto-conversion)
        executed_action = result.get('action', action.value) if isinstance(result, dict) else action.value
        self.action_history.append({
            'round': self.round_number,
            'turn': self.turn_number,
            'player_id': player_id,
            'action': executed_action,  # Use actual executed action
            'result': result
        })
        
        player['actions_taken'] += 1
        self.turn_number += 1
        
        # Check for eliminations
        self._check_eliminations()
        
        return result
    
    # ========================================================================
    # ACTION IMPLEMENTATIONS
    # ========================================================================
    
    def _get_action_cost(self, action: ActionType) -> int:
        """Get the energy cost for an action (REST is negative = gain)"""
        cost_map = {
            ActionType.MOVE: 2,
            ActionType.ATTACK_PLAYER: 4,
            ActionType.SOLVE_CTF: 5,
            ActionType.CLAIM_TERRITORY: 3,
            ActionType.REST: -3,  # REST gains energy
            ActionType.SCOUT: 2,
            ActionType.DEFEND: 2,  # Block attacks for one round
            ActionType.STEAL_PROGRESS: 4
        }
        return cost_map.get(action, 0)
    
    def _execute_action(self, player_id: int, action: ActionType, data: Optional[Dict]) -> Dict:
        """Execute specific action with energy pre-check"""
        player = self.players[player_id]
        
        # PRE-CHECK: Verify player can afford action (REST is special case with negative cost)
        action_cost = self._get_action_cost(action)
        if action_cost > 0 and player['energy'] < action_cost:
            return {
                'error': 'Insufficient energy',
                'success': False,
                'energy_required': action_cost,
                'energy_available': player['energy'],
                'action': action.value
            }
        
        action_map = {
            ActionType.MOVE: self._action_move,
            ActionType.ATTACK_PLAYER: self._action_attack_player,
            ActionType.SOLVE_CTF: self._action_solve_ctf,
            ActionType.CLAIM_TERRITORY: self._action_claim_territory,
            ActionType.REST: self._action_rest,
            ActionType.SCOUT: self._action_scout,
            ActionType.DEFEND: self._action_defend,
            ActionType.STEAL_PROGRESS: self._action_steal_progress
        }
        
        action_func = action_map.get(action)
        if action_func:
            result = action_func(player_id, data)
            
            # POST-ACTION: Clamp energy at 0 and eliminate if depleted
            player['energy'] = max(0, player['energy'])
            if player['energy'] == 0 and player['alive']:
                print(f"⚡ Player {player_id} energy depleted (0 energy) - ELIMINATING")
                self.green_agent.eliminate_player(player_id, 'energy_depleted')
                result['eliminated_reason'] = 'energy_depleted'
            
            return result
        else:
            return {'error': 'Invalid action', 'success': False}
    
    def _action_move(self, player_id: int, data: Optional[Dict]) -> Dict:
        """Move to an adjacent hexagon"""
        player = self.players[player_id]
        energy_before = player['energy']
        
        if not data or 'target' not in data:
            return {'error': 'No target specified', 'success': False, 'energy_before': energy_before, 'energy_after': energy_before}
        
        target_hex = tuple(data['target'])
        current_pos = player['position']
        
        # Check if adjacent
        if not self._is_adjacent(current_pos, target_hex):
            # Penalize invalid move
            player.setdefault('_bad_moves', 0)
            player['_bad_moves'] += 1
            player['energy'] = max(0, player['energy'] - 1)
            
            result = {
                'error': 'Target not adjacent',
                'success': False,
                'energy_before': energy_before,
                'energy_after': player['energy'],
                'details': {'strikes': player['_bad_moves']}
            }
            
            # DQ after 3 bad moves
            if player['_bad_moves'] >= 3:
                player['alive'] = False
                player['status'] = PlayerStatus.ELIMINATED.value
                result['eliminated'] = True
                result['elimination_reason'] = 'Repeated illegal moves (3 strikes)'
                print(f"❌ Player {player_id} DISQUALIFIED: 3 illegal move attempts")
            
            return result
        
        # Check if target exists
        if target_hex not in self.hexagons:
            # Penalize invalid move
            player.setdefault('_bad_moves', 0)
            player['_bad_moves'] += 1
            player['energy'] = max(0, player['energy'] - 1)
            
            result = {
                'error': 'Invalid target hexagon',
                'success': False,
                'energy_before': energy_before,
                'energy_after': player['energy'],
                'details': {'strikes': player['_bad_moves']}
            }
            
            # DQ after 3 bad moves
            if player['_bad_moves'] >= 3:
                player['alive'] = False
                player['status'] = PlayerStatus.ELIMINATED.value
                result['eliminated'] = True
                result['elimination_reason'] = 'Repeated illegal moves (3 strikes)'
                print(f"❌ Player {player_id} DISQUALIFIED: 3 illegal move attempts")
            
            return result
        
        # Check energy
        if player['energy'] < 2:
            return {'error': 'Insufficient energy', 'success': False, 'energy_before': energy_before, 'energy_after': energy_before}
        
        # Execute move
        player['position'] = target_hex
        player['energy'] -= 2
        player['_bad_moves'] = 0  # Reset strikes on successful move
        self._update_vision(player_id)
        
        # Check for resource hex bonus (ONE-TIME ONLY!)
        hex_data = self.hexagons[target_hex]
        bonus_msg = ""
        if hex_data['type'] == HexType.RESOURCE and not hex_data.get('bonus_consumed', False):
            player['energy'] = min(player['max_energy'], player['energy'] + 3)
            hex_data['bonus_consumed'] = True  # Mark bonus as consumed
            bonus_msg = " +3 energy from resource hex (first time bonus)!"
        
        return {
            'action': 'move',
            'success': True,
            'position': target_hex,
            'energy': player['energy'],
            'message': f'Moved to {target_hex}{bonus_msg}'
        }
    
    def _action_attack_player(self, player_id: int, data: Optional[Dict]) -> Dict:
        """Attack an adjacent player"""
        attacker = self.players[player_id]
        
        if not data or 'target_player' not in data:
            return {'error': 'No target player specified', 'success': False}
        
        target_id = data['target_player']
        if target_id not in self.players:
            return {'error': 'Invalid target player', 'success': False}
        
        target = self.players[target_id]
        
        # Check if target is alive
        if target['status'] != PlayerStatus.ALIVE:
            return {'error': 'Target player is not alive', 'success': False}
        
        # Check if adjacent
        if not self._is_adjacent(attacker['position'], target['position']):
            return {'error': 'Target not adjacent', 'success': False}
        
        # Check if target is defending
        if target.get('defending', False):
            return {
                'action': 'attack_player',
                'success': False,
                'message': f'Player {target_id} is defending. Attack blocked!',
                'energy': attacker['energy']
            }
        
        # Check energy
        if attacker['energy'] < 4:
            return {'error': 'Insufficient energy', 'success': False}
        
        # Calculate damage (simplified - no terrain bonuses)
        total_damage = attacker['attack_power']
        
        # Apply defender's shield and defense
        actual_damage = max(0, total_damage - target['shield'] - target['defense_power'])
        
        # Execute attack
        attacker['energy'] -= 4
        target['shield'] = max(0, target['shield'] - total_damage)
        target['health'] -= actual_damage
        
        # Steal resources on successful hit
        stolen_energy = 0
        if actual_damage > 0:
            stolen_energy = min(3, target['energy'])
            target['energy'] -= stolen_energy
            attacker['energy'] = min(attacker['max_energy'], attacker['energy'] + stolen_energy)
        
        # Check for elimination
        eliminated = False
        progress_stolen = 0
        if target['health'] <= 0:
            self.green_agent.eliminate_player(target_id, 'combat')
            attacker['kills'] += 1
            # Steal some CTF progress
            progress_stolen = target['ctf_progress'] * 0.3
            attacker['ctf_progress'] = min(100, attacker['ctf_progress'] + progress_stolen)
            eliminated = True
        
        return {
            'action': 'attack_player',
            'success': True,
            'damage_dealt': actual_damage,
            'energy_stolen': stolen_energy,
            'target_health': target['health'],
            'attacker_energy': attacker['energy'],
            'eliminated': eliminated,
            'progress_stolen': progress_stolen,
            'message': f'Attacked Player {target_id}, dealt {actual_damage} damage'
        }
    
    def _action_solve_ctf(self, player_id: int, data: Optional[Dict]) -> Dict:
        """Attempt to solve the CTF challenge"""
        player = self.players[player_id]
        
        # Check energy
        if player['energy'] < 5:
            return {'error': 'Insufficient energy', 'success': False}
        
        player['energy'] -= 5
        player['ctf_attempts'] += 1
        
        # Get flag attempt from AI
        flag_attempt = data.get('flag') if data else None
        
        if flag_attempt:
            # Validate flag with Green Agent
            is_valid = self.green_agent.validate_flag(player_id, flag_attempt)
            
            if is_valid:
                # INSTANT WIN!
                self._declare_winner(player_id)
                return {
                    'action': 'solve_ctf',
                    'success': True,
                    'flag_valid': True,
                    'energy': player['energy'],
                    'message': f'🏆 CORRECT FLAG! Player {player_id} WINS!',
                    'game_over': True
                }
        
        # Wrong flag - gain progress
        progress_gain = self._calculate_ctf_progress_gain(player)
        player['ctf_progress'] = min(100, player['ctf_progress'] + progress_gain)
        
        # Unlock hints at milestones
        hints_unlocked = []
        if player['ctf_progress'] >= 25 and len(player['ctf_hints']) == 0:
            player['ctf_hints'].append(self.ctf_hints[0])
            hints_unlocked.append(self.ctf_hints[0])
        if player['ctf_progress'] >= 50 and len(player['ctf_hints']) == 1:
            player['ctf_hints'].append(self.ctf_hints[1])
            hints_unlocked.append(self.ctf_hints[1])
        if player['ctf_progress'] >= 75 and len(player['ctf_hints']) == 2:
            player['ctf_hints'].append(self.ctf_hints[2])
            hints_unlocked.append(self.ctf_hints[2])
        
        # Track objective action
        player['last_actions'].append('solve_ctf')
        if len(player['last_actions']) > 5:
            player['last_actions'].pop(0)
        player['since_objective'] = 0  # Reset objective timer
        
        return {
            'action': 'solve_ctf',
            'success': False,
            'flag_valid': False,
            'energy': player['energy'],
            'ctf_progress': player['ctf_progress'],
            'hints_unlocked': hints_unlocked,
            'message': f'Wrong flag. Progress: {player["ctf_progress"]:.1f}%'
        }
    
    def _calculate_ctf_progress_gain(self, player: Dict) -> float:
        """Calculate how much CTF progress to gain from an attempt"""
        base_gain = random.uniform(5, 15)
        territory_bonus = len(player['territories']) * 2
        attempt_bonus = min(player['ctf_attempts'] * 1.5, 10)
        energy_penalty = 0 if player['energy'] >= 5 else 5
        
        total_gain = base_gain + territory_bonus + attempt_bonus - energy_penalty
        return max(0, total_gain)
    
    def _action_claim_territory(self, player_id: int, data: Optional[Dict]) -> Dict:
        """Claim the current hexagon as territory"""
        player = self.players[player_id]
        current_hex = player['position']
        hex_data = self.hexagons[current_hex]
        
        # Already yours? Auto-push them to move toward unowned hex (safety valve)
        if hex_data['owner'] == player_id or current_hex in player['territories']:
            # Find nearest unowned hex and auto-move
            target = self._find_nearest_unowned_for_player(player_id)
            if target and player['energy'] >= 2:
                print(f"🔄 Auto-converting bad CLAIM → MOVE for Player {player_id}")
                # Execute move and return move result (not claim result)
                move_result = self._action_move(player_id, {'target': target})
                # Log as "auto_move" to make conversion explicit
                if isinstance(move_result, dict):
                    move_result['action'] = 'auto_move'
                    move_result['reason'] = 'anti_stall_claim_owned'
                    move_result['original_action'] = 'claim_territory'
                return move_result
            
            # Can't move, return error
            return {
                'action': 'claim_territory',
                'success': False,
                'error': 'Already owned',
                'error_code': 'already_owned',
                'position': current_hex,
                'territories': len(player['territories']),
                'income': player['territory_income'],
                'energy': player['energy'],
                'message': 'Already owned. Move to a new hex to claim.'
            }
        
        # Check if already owned by another player
        if hex_data['owner'] is not None and hex_data['owner'] != player_id:
            return {'error': 'Hexagon owned by another player', 'success': False}
        
        # Check energy
        if player['energy'] < 3:
            return {'error': 'Insufficient energy', 'success': False}
        
        # Claim territory
        player['energy'] -= 3
        hex_data['owner'] = player_id
        if current_hex not in player['territories']:
            player['territories'].append(current_hex)
            player['territory_income'] += 1
        
        # Reset idle streak (this is an objective action)
        player['idle_streak'] = 0
        
        return {
            'action': 'claim_territory',
            'success': True,
            'position': current_hex,
            'territories': len(player['territories']),
            'income': player['territory_income'],
            'energy': player['energy'],
            'message': f'Claimed territory. Income: +{player["territory_income"]} energy/round'
        }
    
    def _action_rest(self, player_id: int, data: Optional[Dict]) -> Dict:
        """Rest to recover energy and health"""
        player = self.players[player_id]
        
        # Anti-REST spam: don't rest twice in a row if energy is decent
        if player['last_actions'][-1:] == ['rest'] and player['energy'] >= 4:
            print(f"⚠️ Preventing REST spam for Player {player_id} - converting to MOVE")
            target = self._find_nearest_unowned_for_player(player_id)
            if target and player['energy'] >= 2:
                move_result = self._action_move(player_id, {'target': target})
                if isinstance(move_result, dict):
                    move_result['action'] = 'auto_move'
                    move_result['reason'] = 'anti_stall_rest_spam'
                    move_result['original_action'] = 'rest'
                return move_result
        
        # Recover energy
        energy_gain = 3 + player['territory_income']
        player['energy'] = min(player['max_energy'], player['energy'] + energy_gain)
        
        # Recover health
        player['health'] = min(100, player['health'] + 10)
        
        # Gain shield if on fortified hexagon
        hex_defense = self.hexagons[player['position']]['defense']
        if hex_defense > 0:
            player['shield'] = min(20, player['shield'] + hex_defense * 2)
        
        # Track action
        player['last_actions'].append('rest')
        if len(player['last_actions']) > 5:
            player['last_actions'].pop(0)
        player['since_objective'] += 1
        
        return {
            'action': 'rest',
            'success': True,
            'energy': player['energy'],
            'health': player['health'],
            'shield': player['shield'],
            'message': f'Rested. Energy: {player["energy"]}, Health: {player["health"]}'
        }
    
    def _action_scout(self, player_id: int, data: Optional[Dict]) -> Dict:
        """Scout nearby area to reveal fog of war"""
        player = self.players[player_id]
        
        # Check energy
        if player['energy'] < 2:
            return {'error': 'Insufficient energy', 'success': False}
        
        # Anti-SCOUT spam: check if there are unseen neighbors
        current_pos = player['position']
        neighbors = self._get_adjacent_hexagons(current_pos)
        unseen_neighbors = [nb for nb in neighbors if self._coord_key(nb) not in player['seen_tiles']]
        
        # If nothing new to scout, convert to MOVE
        if not unseen_neighbors and len(player['seen_tiles']) > 3:
            print(f"⚠️ Preventing SCOUT spam for Player {player_id} - converting to MOVE")
            target = self._find_nearest_unowned_for_player(player_id)
            if target and player['energy'] >= 2:
                move_result = self._action_move(player_id, {'target': target})
                if isinstance(move_result, dict):
                    move_result['action'] = 'auto_move'
                    move_result['reason'] = 'anti_stall_scout_spam'
                    move_result['original_action'] = 'scout'
                return move_result
        
        player['energy'] -= 2
        
        # Mark current position and neighbors as seen
        player['seen_tiles'].add(self._coord_key(current_pos))
        for nb in neighbors:
            player['seen_tiles'].add(self._coord_key(nb))
        
        # Temporarily increase vision range
        original_vision = player['vision_range']
        player['vision_range'] = original_vision + 2
        self._update_vision(player_id)
        
        # Gather intelligence
        intel = {
            'visible_players': player['visible_players'],
            'player_info': {
                pid: {
                    'position': list(self.players[pid]['position']),
                    'health': self.players[pid]['health'],
                    'energy': self.players[pid]['energy']
                }
                for pid in player['visible_players']
            },
            'claimed_territories': {
                str(hex_coord): self.hexagons[hex_coord]['owner']
                for hex_coord in player['visible_hexagons']
                if self.hexagons[hex_coord]['owner'] is not None
            }
        }
        
        # Reset vision range
        player['vision_range'] = original_vision
        self._update_vision(player_id)
        
        # Track action
        player['last_actions'].append('scout')
        if len(player['last_actions']) > 5:
            player['last_actions'].pop(0)
        player['since_objective'] += 1
        
        return {
            'action': 'scout',
            'success': True,
            'energy': player['energy'],
            'intel': intel,
            'message': f'Scouted area. Found {len(player["visible_players"])} players'
        }
    
    def _coord_key(self, coord) -> str:
        """Convert coordinate to string key"""
        return f"{coord[0]},{coord[1]}"
    
    def _action_defend(self, player_id: int, data: Optional[Dict]) -> Dict:
        """Defend - blocks attacks for one round"""
        player = self.players[player_id]
        
        # Deduct energy (pre-check done in _execute_action)
        player['energy'] -= 2
        
        # Set defending flag for this round
        player['defending'] = True
        
        return {
            'action': 'defend',
            'success': True,
            'energy': player['energy'],
            'message': 'Defending. Attacks blocked this round.'
        }
    
    def _action_steal_progress(self, player_id: int, data: Optional[Dict]) -> Dict:
        """Steal CTF progress from adjacent vulnerable player"""
        attacker = self.players[player_id]
        
        if not data or 'target_player' not in data:
            return {'error': 'No target player specified', 'success': False}
        
        target_id = data['target_player']
        if target_id not in self.players:
            return {'error': 'Invalid target player', 'success': False}
        
        target = self.players[target_id]
        
        # Check if target is alive
        if target['status'] != PlayerStatus.ALIVE:
            return {'error': 'Target player is not alive', 'success': False}
        
        # Check if adjacent
        if not self._is_adjacent(attacker['position'], target['position']):
            return {'error': 'Target not adjacent', 'success': False}
        
        # Check energy
        if attacker['energy'] < 6:
            return {'error': 'Insufficient energy', 'success': False}
        
        # Check if target is vulnerable
        if target['health'] > 50:
            return {'error': 'Target too strong to steal from', 'success': False}
        
        # Execute steal
        attacker['energy'] -= 6
        
        # Steal percentage of progress
        stolen_progress = target['ctf_progress'] * 0.4
        target['ctf_progress'] = max(0, target['ctf_progress'] - stolen_progress)
        attacker['ctf_progress'] = min(100, attacker['ctf_progress'] + stolen_progress)
        
        # Chance to steal hints
        hints_stolen = []
        if random.random() < 0.5 and len(target['ctf_hints']) > 0:
            stolen_hint = target['ctf_hints'].pop()
            if stolen_hint not in attacker['ctf_hints']:
                attacker['ctf_hints'].append(stolen_hint)
                hints_stolen.append(stolen_hint)
        
        # Target takes damage
        target['health'] -= 15
        
        return {
            'action': 'steal_progress',
            'success': True,
            'progress_stolen': stolen_progress,
            'hints_stolen': hints_stolen,
            'attacker_progress': attacker['ctf_progress'],
            'target_health': target['health'],
            'energy': attacker['energy'],
            'message': f'Stole {stolen_progress:.1f}% CTF progress from Player {target_id}'
        }
    
    # ========================================================================
    # GAME STATE & MANAGEMENT
    # ========================================================================
    
    def _check_eliminations(self):
        """Check if any players should be eliminated"""
        for player_id, player in self.players.items():
            if player['status'] == PlayerStatus.ALIVE:
                # Health check
                if player['health'] <= 0:
                    self.green_agent.eliminate_player(player_id, 'health_depleted')
                # Energy check
                elif player['energy'] < 0:
                    self.green_agent.eliminate_player(player_id, 'energy_depleted')
    
    def _declare_winner(self, player_id: int, timeout: bool = False):
        """Declare a winner and mark losers appropriately"""
        self.winner = player_id
        self.game_over = True
        self.players[player_id]['status'] = PlayerStatus.WINNER
        
        # Mark other alive players based on win type
        loser_status = PlayerStatus.LOST_TIMEOUT if timeout else PlayerStatus.ELIMINATED
        
        for pid, player in self.players.items():
            if pid != player_id and player['status'] == PlayerStatus.ALIVE:
                player['status'] = loser_status
                if timeout:
                    print(f"  Player {pid}: lost by timeout tiebreak (graceful loss)")
    
    def _rank_on_timeout(self) -> Optional[int]:
        """
        Rank players by objective progress on timeout
        Prevents campers from winning by just surviving
        Returns: winner player_id or None
        """
        alive_players = self.get_alive_players()
        if not alive_players:
            return None
        
        def score_player(pid):
            """Score a player based on objective progress"""
            p = self.players[pid]
            return (
                3.0 * p['ctf_progress'] +           # CTF attempts / progress (most important)
                2.0 * len(p['territories']) +       # Map control
                1.0 * len(p.get('seen_tiles', set())) +  # Exploration
                0.5 * p['energy'] +                 # Leftover resources (tie-break)
                1.0 * p.get('kills', 0) -           # Combat engagement
                0.5 * p.get('_bad_moves', 0)        # Penalty for illegal spam
            )
        
        # Find player with highest score
        winner_id = max(alive_players, key=score_player)
        winner_score = score_player(winner_id)
        
        print(f"⏰ TIMEOUT RANKING:")
        for pid in alive_players:
            score = score_player(pid)
            p = self.players[pid]
            print(f"   Player {pid}: score={score:.1f} (CTF={p['ctf_progress']:.1f}%, "
                  f"territories={len(p['territories'])}, energy={p['energy']})")
        
        print(f"🏆 Player {winner_id} wins by timeout ranking (score={winner_score:.1f})!")
        
        return winner_id
    
    def get_alive_players(self) -> List[int]:
        """Get list of alive players"""
        return [
            pid for pid, player in self.players.items() 
            if player['status'] == PlayerStatus.ALIVE
        ]
    
    def get_game_state(self) -> Dict:
        """Get current game state"""
        elapsed_time = time.time() - self.start_time if self.start_time else 0
        
        return {
            'round_number': self.round_number,
            'turn_number': self.turn_number,
            'elapsed_time': elapsed_time,
            'max_time': self.max_time,
            'max_rounds': self.max_rounds,
            'game_over': self.game_over,
            'winner': self.winner,
            'players': {
                pid: {
                    'id': pid,
                    'name': p['name'],
                    'position': list(p['position']),
                    'energy': p['energy'],
                    'health': p['health'],
                    'shield': p['shield'],
                    'status': p['status'].value,
                    'ctf_progress': p['ctf_progress'],
                    'territories': len(p['territories']),
                    'kills': p['kills'],
                    'color': p['color'],
                    'seen': list(p['seen_tiles'])  # Convert set to list for JSON
                }
                for pid, p in self.players.items()
            },
            'hexagons': {
                f"{q},{r}": {
                    'type': hex_data['type'].value,
                    'owner': hex_data['owner'],
                    'defense': hex_data['defense']
                }
                for (q, r), hex_data in self.hexagons.items()
            },
            'alive_players': self.get_alive_players(),
            'action_history': self.action_history[-10:]  # Last 10 actions
        }


class GreenAgent:
    """
    Green Agent - Judge and Match Controller
    Enforces fair rules, validates flags, tracks actions, decides winners
    """
    
    def __init__(self, game: CTFHungerGame):
        self.game = game
        self.correct_flag = "flag{hexagonal_hunger_games_victory_2025}"  # Default flag
        self.validation_count = 0
        try:
            self.client = OpenAI(api_key=Config.OPENAI_API_KEY)  # LLM for validation
        except OpenAIError as e:
            print(" == error ==")
            print(e)

        self.validation_history = []  # Store all validations for frontend
        
    def set_correct_flag(self, flag: str):
        """Set the correct flag for this challenge"""
        self.correct_flag = flag
        
    def validate_flag(self, player_id: int, flag_attempt: str) -> bool:
        """Validate if a flag attempt is correct"""
        self.validation_count += 1
        
        print(f"🟢 Green Agent: Validating flag from Player {player_id}")
        print(f"   Attempt: {flag_attempt}")
        
        is_valid = flag_attempt == self.correct_flag
        
        if is_valid:
            print(f"   ✅ VALID FLAG! Player {player_id} wins!")
        else:
            print(f"   ❌ Invalid flag")
            
        return is_valid
    
    def eliminate_player(self, player_id: int, reason: str):
        """Eliminate a player from the game"""
        player = self.game.players[player_id]
        player['status'] = PlayerStatus.ELIMINATED
        
        # Release all territories
        for hex_coord in player['territories']:
            self.game.hexagons[hex_coord]['owner'] = None
        
        print(f"💀 Green Agent: Player {player_id} eliminated - {reason}")
        
        # Check if only one player remains
        alive_players = self.game.get_alive_players()
        if len(alive_players) == 1:
            self.game._declare_winner(alive_players[0])
        elif len(alive_players) == 0:
            self.game.game_over = True
            print("Game Over - No survivors!")
    
    def timeout_elimination(self, player_id: int) -> Dict:
        """Eliminate player due to timeout"""
        self.eliminate_player(player_id, 'timeout')
        return {
            'error': 'Timeout',
            'eliminated': True,
            'player_id': player_id
        }
    
    def validate_action(self, player_id: int, action: ActionType, data: Dict) -> Dict:
        """
        LLM-powered validation of player action BEFORE execution.
        Returns: {
            'legal': bool,
            'reasoning': str,
            'player_id': int,
            'action': str
        }
        """
        player = self.game.players[player_id]
        action_cost = self.game._get_action_cost(action)
        
        # Get current hex information
        current_pos = tuple(player['position'])
        current_hex = self.game.hexagons.get(current_pos, {})
        hex_owner = current_hex.get('owner')
        hex_type = current_hex.get('type', 'unknown')
        
        # Get adjacent hexes information for movement validation
        adjacent_hexes = []
        if action == ActionType.MOVE and data and 'target' in data:
            target = data['target']
            if isinstance(target, dict):
                target_pos = (target.get('q'), target.get('r'))
            elif isinstance(target, (list, tuple)) and len(target) >= 2:
                target_pos = (target[0], target[1])
            else:
                target_pos = None
            
            if target_pos and target_pos in self.game.hexagons:
                adjacent_hexes.append({
                    'position': target_pos,
                    'owner': self.game.hexagons[target_pos].get('owner'),
                    'type': self.game.hexagons[target_pos].get('type')
                })
        
        # Build detailed context for LLM
        prompt = f"""You are the Green Agent referee in a CTF Hunger Games competition.

PLAYER STATE:
- Player {player_id} position: {player['position']}
- Player {player_id} energy: {player['energy']}/{player.get('max_energy', 15)}
- Player {player_id} health: {player['health']}/100
- Player {player_id} status: {player['status']}

CURRENT HEX INFORMATION:
- Position: {current_pos}
- Type: {hex_type}
- Owner: {hex_owner if hex_owner else 'unowned (None)'}
- Is owned by this player: {hex_owner == player_id}
- Is unowned: {hex_owner is None}

INTENDED ACTION:
- Action: {action.value}
- Data: {json.dumps(data)}
- Energy cost: {action_cost}

VALIDATION RULES:
1. Player must be ALIVE (status = 'alive')
2. Player must have sufficient energy (current: {player['energy']}, required: {action_cost})
3. MOVE: Target must be adjacent and exist on board
4. ATTACK_PLAYER: Target must be adjacent and alive
5. CLAIM_TERRITORY: Must be on an UNOWNED hex (owner must be None/null)
6. REST: Always allowed if alive
7. SCOUT: Always allowed if have energy
8. DEFEND: Always allowed if have energy
9. SOLVE_CTF: Must have enough energy
10. STEAL_PROGRESS: Target must be adjacent and alive

IMPORTANT: If the current hex owner is None or null, it IS unowned and CAN be claimed!

TASK: Determine if this action is LEGAL or ILLEGAL.

Respond in JSON format:
{{
  "legal": true/false,
  "reasoning": "Brief explanation why this action is legal or illegal (1-2 sentences)"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Store validation
            validation_result = {
                'player_id': player_id,
                'action': action.value,
                'legal': result.get('legal', False),
                'reasoning': result.get('reasoning', 'No reasoning provided'),
                'timestamp': time.time(),
                'round': self.game.round_number
            }
            
            print(f"🟢 Green Agent: Player {player_id} action {action.value} - {'✅ LEGAL' if validation_result['legal'] else '❌ ILLEGAL'}")
            print(f"   Reasoning: {validation_result['reasoning']}")
            
        except Exception as e:
            # Fallback to always legal if LLM fails
            print(f"⚠️ Green Agent LLM error: {e}")
            validation_result = {
                'player_id': player_id,
                'action': action.value,
                'legal': True,
                'reasoning': f'LLM validation failed, allowing action. Error: {str(e)}',
                'timestamp': time.time(),
                'round': self.game.round_number
            }
        
        self.validation_history.append(validation_result)
        return validation_result
    
    def get_round_validations(self, round_num: int) -> List[Dict]:
        """Get all validations for a specific round"""
        return [v for v in self.validation_history if v['round'] == round_num]
    
    def clear_round_validations(self):
        """Clear validations for new round"""
        current_round = self.game.round_number
        self.validation_history = [v for v in self.validation_history if v['round'] != current_round]
