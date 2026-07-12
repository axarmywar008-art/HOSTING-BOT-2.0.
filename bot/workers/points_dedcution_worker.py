import asyncio
import logging
import datetime
from bot.database.db import database
from bot.deployment.engine import deployment_engine
from bot.services.log_service import owner_log

logger = logging.getLogger(__name__)


class PointDeductionWorker:
    """
    Background worker that deducts points daily from users with active deployments.
    If a user runs out of points, their bot is automatically stopped.
    """
    
    def __init__(self):
        self._running = False
        self._task = None
        self.DAILY_COST = 2  # Points per day
        self.MINIMUM_POINTS = 60  # Minimum points required to deploy

    async def start(self):
        """Start the point deduction worker."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("PointDeductionWorker started")
        try:
            await owner_log.send_log("worker_started", worker="PointDeductionWorker")
        except Exception:
            pass

    async def stop(self):
        """Stop the point deduction worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("PointDeductionWorker stopped")

    async def _run_loop(self):
        """Main loop that runs every hour and checks for deductions."""
        while self._running:
            try:
                await self._process_deductions()
            except Exception as e:
                logger.error(f"Point deduction error: {e}")
            await asyncio.sleep(3600)  # Run every hour

    async def _process_deductions(self):
        """Process point deductions for all active deployments."""
        now = datetime.datetime.utcnow()
        
        # Get all active deployment point records
        records = await database.get_all_active_deployment_points()
        
        if not records:
            return

        logger.info(f"Processing point deductions for {len(records)} active deployments")

        for record in records:
            deployment_id = record["deployment_id"]
            user_id = record["user_id"]
            
            # Check if it's time for deduction
            next_deduction = record.get("next_deduction")
            if next_deduction and now < next_deduction:
                continue

            try:
                # Check user's current points
                points = await database.get_points_balance(user_id)
                
                if points < self.DAILY_COST:
                    # Not enough points - stop the deployment
                    logger.warning(f"User {user_id} has insufficient points ({points}) for deployment {deployment_id}")
                    await self._stop_deployment(deployment_id, user_id, points)
                    continue

                # Deduct points
                success = await database.deduct_points(
                    user_id, 
                    self.DAILY_COST, 
                    reason=f"daily_deployment_{deployment_id[:8]}"
                )
                
                if success:
                    new_balance = await database.get_points_balance(user_id)
                    
                    # Update deployment point record
                    await database.update_deployment_point_record(
                        deployment_id,
                        {
                            "points_remaining": new_balance,
                            "last_deduction": now,
                            "next_deduction": now + datetime.timedelta(days=1)
                        }
                    )
                    
                    # Check if points are getting low
                    if new_balance < 10:
                        await self._send_low_points_warning(user_id, deployment_id, new_balance)
                    
                    logger.info(f"Deducted {self.DAILY_COST} points from user {user_id} for deployment {deployment_id}. Remaining: {new_balance}")
                else:
                    logger.error(f"Failed to deduct points from user {user_id}")

            except Exception as e:
                logger.error(f"Error processing deduction for {deployment_id}: {e}")

    async def _stop_deployment(self, deployment_id: str, user_id: int, points_remaining: int):
        """Stop a deployment due to insufficient points."""
        try:
            # Get deployment
            dep = await database.get_deployment(deployment_id)
            if not dep:
                logger.warning(f"Deployment {deployment_id} not found")
                await database.mark_deployment_points_inactive(deployment_id)
                return

            # Stop the deployment
            await deployment_engine.stop_deployment(deployment_id)
            
            # Update deployment status
            await database.update_deployment(deployment_id, {
                "status": "stopped_due_to_points",
                "points_stopped_at": points_remaining
            })
            
            # Mark points record as inactive
            await database.mark_deployment_points_inactive(deployment_id)
            
            # Notify user
            try:
                await owner_log.send_user_notification(
                    user_id,
                    f"<b>⚠ Bot Stopped - Insufficient Points</b>\n\n"
                    f"Your bot <code>{dep.get('repo_url', 'Unknown')}</code> has been stopped because you ran out of points.\n\n"
                    f"<b>Points Remaining:</b> {points_remaining}\n"
                    f"<b>Daily Cost:</b> {self.DAILY_COST} points/day\n\n"
                    f"Please contact an admin to add more points to your account."
                )
            except Exception:
                pass
            
            # Log to admin
            try:
                await owner_log.send_log(
                    "bot_stopped_points",
                    user_id=str(user_id),
                    deployment_id=deployment_id[:8],
                    points_remaining=str(points_remaining),
                    reason="Insufficient points"
                )
            except Exception:
                pass
            
            logger.info(f"Stopped deployment {deployment_id} due to insufficient points for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error stopping deployment {deployment_id}: {e}")

    async def _send_low_points_warning(self, user_id: int, deployment_id: str, points_remaining: int):
        """Send a warning to user when points are low."""
        try:
            await owner_log.send_user_notification(
                user_id,
                f"<b>⚠ Low Points Warning</b>\n\n"
                f"Your bot is consuming <b>{self.DAILY_COST}</b> points per day.\n"
                f"<b>Points Remaining:</b> {points_remaining}\n\n"
                f"Please contact an admin to add more points before your bot stops."
            )
        except Exception as e:
            logger.error(f"Error sending low points warning: {e}")

    async def get_deployment_point_status(self, deployment_id: str) -> dict:
        """Get the point status for a deployment."""
        record = await database.get_deployment_point_record(deployment_id)
        if not record:
            return {"status": "not_tracked"}
        
        dep = await database.get_deployment(deployment_id)
        return {
            "status": record.get("status", "unknown"),
            "daily_cost": record.get("daily_cost", self.DAILY_COST),
            "points_remaining": record.get("points_remaining", 0),
            "last_deduction": record.get("last_deduction"),
            "next_deduction": record.get("next_deduction")
        }


point_deduction_worker = PointDeductionWorker()
