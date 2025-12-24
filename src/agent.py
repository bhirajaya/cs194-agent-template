from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from messenger import Messenger

import json
from ctf_hunger_game import CTFHungerGame
from ctf_ai_player import CTFAIPlayer
from game_logger import GameLogger

class Agent:
    def __init__(self):
        self.messenger = Messenger()
        # Initialize other state here

        # Add
        # The engine manages the rules and board state
        self.game = None 
        self.logger = GameLogger()

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Implement your agent logic here.

        Args:
            message: The incoming message
            updater: Report progress (update_status) and results (add_artifact)

        Use self.messenger.talk_to_agent(message, url) to call other agents.
        """
        input_text = get_message_text(message)

        #Add
        try:
            config = json.loads(input_text)
            participants = config.get("participants", {})
        except Exception as e:
            await updater.update_status(
                TaskState.failed, new_agent_text_message(f"Invalid config: {str(e)}")
            )
            return
        
        # 2. Initialize the Game Engine
        challenge_name = config.get("challenge", "Standard CTF Arena")
        self.game = CTFHungerGame(ctf_challenge=challenge_name)
        self.logger.clear_log()
        self.logger.set_game_info(challenge_name, len(participants))
        
        self.game.start_game()

        # 3. Game Loop (The "Run" part)
        for round_num in range(1, 21): # Max 20 rounds
            if self.game.game_over:
                break
            
            await updater.update_status(
                TaskState.working, 
                new_agent_text_message(f"Starting Round {round_num}...")
            )
            
            round_actions = []
            
            for pid in self.game.get_alive_players():
                # Get the URL for this specific player
                player_url = participants.get(str(pid))
                if not player_url:
                    continue

                # Prepare state to send to the player
                state = self.game.get_game_state()
                state["assigned_id"] = pid
                
                # CALL PLAYER (The "A2A" part)
                player_msg = new_agent_text_message(json.dumps(state))
                try:
                    # Talk to the Purple Agent
                    response = await self.messenger.talk_to_agent(player_msg, player_url)
                    response_text = get_message_text(response)
                    decision = json.loads(response_text)
                    
                    # Apply action to the engine
                    result = self.game.execute_turn(
                        pid, 
                        ActionType(decision['action']), 
                        decision.get('data')
                    )
                    round_actions.append({'player_id': pid, 'result': result})
                    
                except Exception as e:
                    logger.error(f"Failed to get move from player {pid}: {e}")

            # Update the status and internal logs
            self.logger.log_round(round_num, round_actions)
            self.game.round_number = round_num

        # 4. Finalize and Upload Artifacts (The "Updater" part)
        winner = self.game.check_winner()
        final_state = self.game.get_game_state()

        result_data = {
            "winner": winner,
            "final game state": final_state
        }

        # # Calculate final stats for the participant being evaluated
        # # (Assuming you are evaluating one participant at a time for the leaderboard)
        # final_score = game.players[str(target_pid)].ctf_progress
        # final_accuracy = game.get_accuracy(target_pid) 

        # # This JSON format allows AgentBeats to populate the leaderboard columns
        # result_data = {
        #     "score": final_score,
        #     "accuracy": final_accuracy
        # }

        # This makes the log viewable on the AgentBeats dashboard
        await updater.add_artifact(
            parts=[Part(root=TextPart(text=json.dumps(self.logger.logs, indent=2)))],
            name="Game Log",
        )

        await updater.update_status(
            TaskState.succeeded, 
            new_agent_text_message(f"Game Over! Winner: Player {winner}"),
            new_agent_text_message(json.dumps(result_data))
        )

        # # Replace this example code with your agent logic

        # await updater.update_status(
        #     TaskState.working, new_agent_text_message("Thinking...")
        # )
        # await updater.add_artifact(
        #     parts=[Part(root=TextPart(text=input_text))],
        #     name="Echo",
        # )
