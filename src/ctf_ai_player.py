"""
AI Player for CTF Hunger Games
Uses OpenAI to make strategic decisions in the hex-based battle royale
"""
from openai import OpenAI
from config import Config
from ctf_hunger_game import ActionType
import random

class CTFAIPlayer:
    """
    AI Player that competes in CTF Hunger Games on hexagonal board
    Makes strategic decisions using OpenAI for movement, combat, and CTF solving
    """
    
    def __init__(self, player_id: int, name: str = None):
        self.player_id = player_id
        self.name = name or f"AI Player {player_id}"
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.strategy_memory = []
    
    # ========================================================================
    # COORDINATE HELPERS
    # ========================================================================
    
    def _k(self, c):
        """Convert (q, r) or [q, r] to 'q,r' string key"""
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            return f"{c[0]},{c[1]}"
        return str(c)
    
    def _t(self, k):
        """Convert 'q,r' string to (q, r) tuple"""
        if isinstance(k, str) and ',' in k:
            parts = k.split(',')
            return (int(parts[0]), int(parts[1]))
        elif isinstance(k, (list, tuple)):
            return tuple(k[:2])
        return k
    
    def _tile_owner(self, game_state: dict, c_tuple) -> int:
        """Get owner of a tile, returns None or player_id"""
        key = self._k(c_tuple)
        tile = game_state.get('hexagons', {}).get(key, {})
        return tile.get('owner')
    
    def _owns_here(self, game_state: dict, player_state: dict) -> bool:
        """Check if player owns the current hexagon"""
        pos = tuple(player_state['position'])
        me = player_state.get('id', self.player_id)
        return self._tile_owner(game_state, pos) == me
    
    def _neighbors(self, c):
        """Get all 6 adjacent hexagon coordinates"""
        q, r = c
        for dq, dr in [(1,0), (1,-1), (0,-1), (-1,0), (-1,1), (0,1)]:
            yield (q+dq, r+dr)
    
    def _exists(self, game_state: dict, c) -> bool:
        """Check if hexagon exists in game"""
        return self._k(c) in game_state.get('hexagons', {})
    
    def _is_unowned(self, game_state: dict, c) -> bool:
        """Check if hex is unowned"""
        return self._tile_owner(game_state, c) is None
        
    def decide_action(self, game_state: dict) -> dict:
        """
        Decide which action to take based on current game state
        Returns: {action: ActionType, data: dict}
        """
        player_state = game_state['players'][self.player_id]
        
        # Quick rule-based decisions for critical situations
        critical_decision = self._check_critical_situations(game_state, player_state)
        if critical_decision:
            return critical_decision
        
        # Get strategic decision from AI
        prompt = self._create_strategy_prompt(game_state, player_state)
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=300
            )
            
            decision = self._parse_ai_decision(response, game_state, player_state)
            self.strategy_memory.append(decision)

            ## Add to show white agent reasoning
            print(f"White Agent Decision")
            # print(f"- Player {self.player_id} decision: {decision}")
            #   Action {decision.action}, Data {decision.data}, Energy {decision.energy}, Reasoning {decision.reasonning} ) ")

            return decision
            
        except Exception as e:
            print(f"Error in AI decision for Player {self.player_id}: {e}")
            return self._fallback_strategy(game_state, player_state)
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for AI"""
        return """You are an expert AI agent competing in a CTF Hunger Games on a hexagonal battlefield.

Your goal: WIN by either:
1. PRIMARY: Solve the CTF challenge first (find the flag)
2. SECONDARY: Eliminate all opponents through strategic combat
3. TERTIARY: Have highest combined score (territory + CTF progress) when time expires

Strategic Principles:
- Balance offense (CTF solving) with defense (combat/positioning)
- Control strategic hexagons for resource generation
- Attack weak opponents to steal their CTF progress
- Manage energy efficiently (know when to rest vs push)
- Use scout to find opponents and avoid strong players

Make smart, calculated decisions based on the current situation."""
    
    def _check_critical_situations(self, game_state: dict, player_state: dict) -> dict:
        """Check for critical situations that need immediate action"""
        energy = player_state['energy']
        health = player_state['health']
        
        # CRITICAL: Very low health - must rest
        if health < 25 and energy >= 0:
            return {
                'action': ActionType.REST,
                'data': {},
                'energy': energy,
                'reason': 'critical_health'
            }
        
        # CRITICAL: Very low energy - must rest
        if energy < 2:
            return {
                'action': ActionType.REST,
                'data': {},
                'energy': energy,
                'reason': 'critical_energy'
            }
        
        # OPPORTUNITY: Very high CTF progress - go for win
        if player_state['ctf_progress'] >= 85 and energy >= 5:
            return {
                'action': ActionType.SOLVE_CTF,
                'data': {'flag': self._generate_educated_guess(player_state)},
                'energy': energy,
                'reason': 'high_progress_win_attempt'
            }
        
        return None
    
    def _create_strategy_prompt(self, game_state: dict, player_state: dict) -> str:
        """Create detailed prompt for AI decision making"""
        
        alive_count = len(game_state['alive_players'])
        round_num = game_state['round_number']
        
        # Get visible enemy info
        visible_enemies = self._get_visible_enemies(game_state, player_state)
        
        prompt = f"""
# SITUATION REPORT - Round {round_num}

## Your Status (Player {self.player_id})
- Position: {player_state['position']}
- Energy: {player_state['energy']}/{player_state.get('max_energy', 15)}
- Health: {player_state['health']}/100
- Shield: {player_state['shield']}
- CTF Progress: {player_state['ctf_progress']:.1f}%
- Territories Owned: {player_state['territories']}
- Kills: {player_state['kills']}

## Battlefield
- Alive Players: {alive_count}/6
- Your Rank: #{self._estimate_rank(game_state, player_state)}/6

## Visible Enemies
{visible_enemies}

## Available Actions
1. **MOVE** (2 energy): Move to adjacent hex. Strategy: explore, flee, chase
2. **ATTACK_PLAYER** (4 energy): Deal damage to adjacent enemy. Can eliminate weak opponents
3. **SOLVE_CTF** (5 energy): Attempt CTF challenge. INSTANT WIN if correct flag!
4. **CLAIM_TERRITORY** (3 energy): Claim current hex for passive energy income
5. **REST** (0 energy): Recover +3 energy, +10 health. Safe option
6. **SCOUT** (2 energy): Reveal nearby area, find enemies
7. **DEFEND** (2 energy): Block all attacks for one round
8. **STEAL_PROGRESS** (4 energy): Steal CTF progress from weak adjacent enemy

## Strategy Guidelines

### Early Game (Rounds 1-5):
- Claim 2-3 territories for passive energy income
- Scout to locate opponents
- Make 1-2 CTF attempts to gain progress

### Mid Game (Rounds 6-12):
- Attack weak opponents to steal progress
- Maintain energy above 50%
- Balance CTF attempts with territorial defense

### Late Game (Rounds 13+):
- If CTF progress > 70%: Focus entirely on solving
- If combat-focused: Eliminate weak players
- All-in aggression or defensive turtle

## Current Situation Analysis
{self._analyze_situation(game_state, player_state)}

## Your Decision
Respond in this EXACT format:
ACTION: <action_name>
TARGET: <target_data_if_needed>
REASONING: <brief explanation>

Example responses:
- "ACTION: SOLVE_CTF\nTARGET: flag{{example}}\nREASONING: High progress, going for win"
- "ACTION: MOVE\nTARGET: [3, 2]\nREASONING: Moving to resource hex"
- "ACTION: ATTACK_PLAYER\nTARGET: 5\nREASONING: Player 5 is weak and adjacent"
- "ACTION: REST\nREASONING: Low energy, need to recover"
"""
        
        return prompt
    
    def _get_visible_enemies(self, game_state: dict, player_state: dict) -> str:
        """Format visible enemy information"""
        visible = player_state.get('visible_players', [])
        if not visible:
            return "No enemies visible (fog of war)"
        
        enemy_info = []
        for enemy_id in visible:
            enemy = game_state['players'][enemy_id]
            distance = self._calculate_distance(
                player_state['position'], 
                enemy['position']
            )
            threat_level = self._assess_threat(player_state, enemy)
            
            enemy_info.append(
                f"- Player {enemy_id}: Health {enemy['health']}, "
                f"Energy {enemy['energy']}, Distance {distance}, "
                f"Threat: {threat_level}"
            )
        
        return "\n".join(enemy_info)
    
    def _calculate_distance(self, pos1, pos2) -> int:
        """Calculate hexagonal distance"""
        q1, r1 = pos1
        q2, r2 = pos2
        return (abs(q1 - q2) + abs(r1 - r2) + abs((q1 + r1) - (q2 + r2))) // 2
    
    def _assess_threat(self, player_state: dict, enemy_state: dict) -> str:
        """Assess threat level of an enemy"""
        if enemy_state['health'] < 30:
            return "LOW (vulnerable)"
        elif enemy_state['health'] < 60:
            return "MEDIUM"
        elif enemy_state['health'] > 80 and enemy_state['energy'] > player_state['energy']:
            return "HIGH (strong)"
        else:
            return "MEDIUM"
    
    def _estimate_rank(self, game_state: dict, player_state: dict) -> int:
        """Estimate player's rank based on CTF progress and health"""
        scores = []
        for pid, p in game_state['players'].items():
            if p['status'] == 'alive':
                score = p['ctf_progress'] + (p['health'] * 0.3) + (p['territories'] * 5)
                scores.append((pid, score))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        for rank, (pid, score) in enumerate(scores, 1):
            if pid == self.player_id:
                return rank
        return len(scores)
    
    def _analyze_situation(self, game_state: dict, player_state: dict) -> str:
        """Analyze current situation and provide insights"""
        round_num = game_state['round_number']
        energy = player_state['energy']
        health = player_state['health']
        progress = player_state['ctf_progress']
        
        insights = []
        
        # Phase analysis
        if round_num <= 5:
            insights.append("📍 EARLY GAME: Focus on territory and exploration")
        elif round_num <= 12:
            insights.append("⚔️ MID GAME: Balance combat and CTF progress")
        else:
            insights.append("🏁 LATE GAME: Push for victory or eliminate threats")
        
        # Resource status
        if energy < 4:
            insights.append("⚠️ LOW ENERGY: REST recommended")
        elif energy > 10:
            insights.append("✅ GOOD ENERGY: Can afford aggressive actions")
        
        # Health status
        if health < 40:
            insights.append("❤️ LOW HEALTH: Avoid combat, REST to recover")
        
        # Progress status
        if progress >= 75:
            insights.append("🎯 HIGH CTF PROGRESS: Consider solving attempt")
        elif progress < 25:
            insights.append("📚 LOW CTF PROGRESS: Need more SOLVE_CTF attempts")
        
        return "\n".join(insights)
    
    def _parse_ai_decision(self, response, game_state: dict, player_state: dict) -> dict:
        """Parse AI response into action decision"""
        try:
            content = response.choices[0].message.content
            lines = content.split('\n')
            
            action_str = None
            target_str = None
            reasoning_str = None
            
            for line in lines:
                line = line.strip()
                if line.startswith('ACTION:'):
                    action_str = line.replace('ACTION:', '').strip().upper()
                elif line.startswith('TARGET:'):
                    target_str = line.replace('TARGET:', '').strip()
                elif line.startswith('REASONING:'):
                    reasoning_str = line.replace('REASONING:', '').strip()
                
            
            # Parse action
            action, data = self._parse_action_and_target(action_str, target_str, game_state, player_state)
            
            return {
                'action': action,
                'data': data,
                'energy': player_state['energy'],
                'reason': reasoning_str
            }
            
        except Exception as e:
            print(f"Error parsing AI decision: {e}")
            return self._fallback_strategy(game_state, player_state)
    
    def _parse_action_and_target(self, action_str: str, target_str: str, game_state: dict, player_state: dict):
        """Parse action and target from AI response"""
        
        if not action_str:
            return self._fallback_strategy(game_state, player_state)
        
        # MOVE
        if 'MOVE' in action_str:
            target_hex = self._parse_hex_target(target_str, player_state)
            return ActionType.MOVE, {'target': target_hex}
        
        # ATTACK_PLAYER
        elif 'ATTACK' in action_str and 'PLAYER' in action_str:
            target_player = self._parse_player_target(target_str, player_state, game_state)
            return ActionType.ATTACK_PLAYER, {'target_player': target_player}
        
        # SOLVE_CTF
        elif 'SOLVE' in action_str or 'CTF' in action_str:
            flag = self._parse_flag(target_str, player_state)
            return ActionType.SOLVE_CTF, {'flag': flag}
        
        # CLAIM_TERRITORY
        elif 'CLAIM' in action_str:
            return ActionType.CLAIM_TERRITORY, {}
        
        # REST
        elif 'REST' in action_str:
            return ActionType.REST, {}
        
        # SCOUT
        elif 'SCOUT' in action_str:
            return ActionType.SCOUT, {}
        
        # DEFEND
        elif 'DEFEND' in action_str:
            return ActionType.DEFEND, {}
        
        # STEAL_PROGRESS
        elif 'STEAL' in action_str:
            target_player = self._parse_player_target(target_str, player_state, game_state)
            return ActionType.STEAL_PROGRESS, {'target_player': target_player}
        
        # Default
        else:
            return ActionType.REST, {}
    
    def _parse_hex_target(self, target_str: str, player_state: dict) -> list:
        """Parse hexagon target from string"""
        if not target_str:
            # Move to random adjacent hex
            return self._get_random_adjacent_hex(player_state['position'])
        
        try:
            # Try to parse [q, r] format
            import re
            numbers = re.findall(r'-?\d+', target_str)
            if len(numbers) >= 2:
                return [int(numbers[0]), int(numbers[1])]
        except:
            pass
        
        return self._get_random_adjacent_hex(player_state['position'])
    
    def _get_random_adjacent_hex(self, position: list) -> list:
        """Get random adjacent hexagon"""
        q, r = position
        directions = [(1,0), (1,-1), (0,-1), (-1,0), (-1,1), (0,1)]
        dq, dr = random.choice(directions)
        return [q + dq, r + dr]
    
    def _nearest_unowned_step(self, game_state: dict, start):
        """Find the first step toward nearest unowned hex using BFS"""
        from collections import deque
        
        if not isinstance(start, tuple):
            start = tuple(start)
        
        seen = {start}
        parent = {start: None}
        queue = deque([start])
        
        while queue:
            cur = queue.popleft()
            
            # Found an unowned hex (not our starting position)
            if (cur != start 
                and self._exists(game_state, cur) 
                and self._is_unowned(game_state, cur)):
                # Backtrack to find the first step from start
                while parent[cur] != start:
                    cur = parent[cur]
                return cur
            
            # Explore neighbors (all hexes are passable now)
            for nb in self._neighbors(cur):
                if (nb in seen 
                    or not self._exists(game_state, nb)):
                    continue
                seen.add(nb)
                parent[nb] = cur
                queue.append(nb)
        
        # No unowned hex found
        return None
    
    def _parse_player_target(self, target_str: str, player_state: dict, game_state: dict) -> int:
        """Parse player target ID"""
        if not target_str:
            # Target random visible enemy
            visible = player_state.get('visible_players', [])
            if visible:
                return random.choice(visible)
            return None
        
        try:
            import re
            numbers = re.findall(r'\d+', target_str)
            if numbers:
                target_id = int(numbers[0])
                if target_id in game_state['players']:
                    return target_id
        except:
            pass
        
        # Fallback: random visible enemy
        visible = player_state.get('visible_players', [])
        return random.choice(visible) if visible else None
    
    def _parse_flag(self, target_str: str, player_state: dict) -> str:
        """Parse flag attempt"""
        if target_str and ('flag{' in target_str.lower() or 'ctf{' in target_str.lower()):
            return target_str
        else:
            return self._generate_educated_guess(player_state)
    
    def _generate_educated_guess(self, player_state: dict) -> str:
        """Generate educated flag guess based on progress and hints"""
        progress = player_state['ctf_progress']
        
        # High progress - try common CTF flags
        if progress >= 80:
            attempts = [
                "flag{hexagonal_hunger_games_victory_2025}",
                "flag{ctf_battle_royale_winner}",
                "flag{ai_agent_supreme}"
            ]
            return random.choice(attempts)
        elif progress >= 50:
            return f"flag{{strategic_victory_{random.randint(100,999)}}}"
        else:
            return f"flag{{attempt_{random.randint(1000,9999)}}}"
    
    def _fallback_strategy(self, game_state: dict, player_state: dict) -> dict:
        """
        Fallback strategy with clear decision logic
        Never gets stuck in claim loops
        """
        me = player_state.get('id', self.player_id)
        pos = tuple(player_state['position'])
        energy = player_state['energy']
        health = player_state['health']
        round_num = game_state['round_number']
        
        # A. Critical health - must rest
        if health < 25:
            return {
                'action': ActionType.REST,
                'data': {},
                'energy': energy,
                'reason': 'critical_health'
            }
        
        # B. High CTF progress - push for win!
        ctf_progress = player_state.get('ctf_progress', 0)
        if ctf_progress >= 50 and energy >= 5:
            print(f"🎯 Player {me} attempting SOLVE_CTF (progress: {ctf_progress}%)")
            return {
                'action': ActionType.SOLVE_CTF,
                'data': {'flag': self._generate_educated_guess(player_state)},
                'energy': energy,
                'reason': 'high_progress_push'
            }
        
        # C. Periodic CTF attempt (every 3 rounds, MUST come before territorial logic!)
        if (round_num % 3 == 0) and energy >= 5:
            print(f"🎯 Player {me} attempting SOLVE_CTF (round {round_num})")
            return {
                'action': ActionType.SOLVE_CTF,
                'data': {'flag': self._generate_educated_guess(player_state)},
                'energy': energy,
                'reason': 'periodic_ctf_attempt'
            }
        
        # C. Check tile ownership at current position
        owner = self._tile_owner(game_state, pos)
        
        # If we stand on an UNOWNED tile → claim it once
        if owner is None and energy >= 3:
            return {
                'action': ActionType.CLAIM_TERRITORY,
                'data': {},
                'energy': energy,
                'reason': ''
            }
        
        # If we already OWN this tile → MOVE to nearest unowned hex
        if owner == me:
            target = self._nearest_unowned_step(game_state, pos)
            if target and energy >= 2:
                print(f"🚶 Player {me} MOVING from owned tile {pos} to {target}")
                return {
                    'action': ActionType.MOVE,
                    'data': {'target': [target[0], target[1]]},
                    'energy': energy,
                    'reason': 'move_from_owned'
                }
            # No unowned hex nearby - scout or rest
            if energy >= 2:
                return {
                    'action': ActionType.SCOUT,
                    'data': {},
                    'energy': energy,
                    'reason': ''
                }
            return {
                'action': ActionType.REST,
                'data': {},
                'energy': energy,
                'reason': ''
            }
        
        # If tile is owned by SOMEONE ELSE → move off it
        if owner is not None and owner != me:
            target = self._nearest_unowned_step(game_state, pos)
            if target and energy >= 2:
                return {
                    'action': ActionType.MOVE,
                    'data': {'target': [target[0], target[1]]},
                    'energy': energy,
                    'reason': 'move_from_enemy_owned'
                }
        
        # D. Low energy - rest
        if energy < 3:
            return {
                'action': ActionType.REST,
                'data': {},
                'energy': energy,
                'reason': ''
            }
        
        # E. Default: scout for intel or rest
        if energy >= 2:
            return {
                'action': ActionType.SCOUT,
                'data': {},
                'energy': energy,
                'reason': ''
            }
        
        return {
            'action': ActionType.REST,
            'data': {},
            'energy': energy,
            'reason': ''
        }
