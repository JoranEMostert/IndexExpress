import asyncio
import logging
import uuid
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger("subagent")


class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class AgentType(Enum):
    QUICKSEARCH = "quicksearch"
    CUSTOM = "custom"


@dataclass
class SubAgent:
    id: str
    name: str
    agent_type: AgentType
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AgentPool:
    """Manages a pool of sub-agents with concurrency control."""
    
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.agents: Dict[str, SubAgent] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._locks: Dict[str, asyncio.Lock] = {}
        
    def create_agent(
        self, 
        name: str, 
        agent_type: AgentType = AgentType.QUICKSEARCH
    ) -> SubAgent:
        """Create a new sub-agent."""
        agent_id = str(uuid.uuid4())[:8]
        agent = SubAgent(
            id=agent_id,
            name=name,
            agent_type=agent_type
        )
        self.agents[agent_id] = agent
        self._locks[agent_id] = asyncio.Lock()
        logger.info(f"Created agent {agent_id} ({name})")
        return agent
    
    async def acquire_slot(self) -> asyncio.Semaphore:
        """Acquire a slot for running an agent task."""
        return await self._semaphore.acquire()
    
    def release_slot(self):
        """Release the semaphore slot."""
        self._semaphore.release()
    
    async def run_agent_task(
        self,
        agent_id: str,
        task_func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Run a task on an agent with concurrency control."""
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} not found")
            
        agent = self.agents[agent_id]
        
        await self.acquire_slot()
        
        try:
            async with self._locks[agent_id]:
                agent.status = AgentStatus.RUNNING
                agent.started_at = datetime.now()
                agent.current_task = task_func.__name__ if hasattr(task_func, '__name__') else "task"
                
            logger.info(f"Agent {agent_id} starting task: {agent.current_task}")
            
            result = await task_func(*args, **kwargs)
            
            async with self._locks[agent_id]:
                agent.status = AgentStatus.COMPLETED
                agent.result = result
                agent.completed_at = datetime.now()
                
            logger.info(f"Agent {agent_id} completed task")
            return result
            
        except Exception as e:
            logger.error(f"Agent {agent_id} failed: {e}")
            async with self._locks[agent_id]:
                agent.status = AgentStatus.FAILED
                agent.error = str(e)
            raise
            
        finally:
            self.release_slot()
    
    def get_available_count(self) -> int:
        """Get number of available agent slots."""
        return self.max_concurrent - sum(
            1 for a in self.agents.values() 
            if a.status == AgentStatus.RUNNING
        )
    
    def get_status(self) -> Dict[str, Any]:
        """Get pool status."""
        return {
            'max_concurrent': self.max_concurrent,
            'available': self.get_available_count(),
            'agents': [
                {
                    'id': a.id,
                    'name': a.name,
                    'type': a.agent_type.value,
                    'status': a.status.value,
                    'task': a.current_task
                }
                for a in self.agents.values()
            ]
        }
    
    async def wait_for_available_slot(self, timeout: Optional[float] = None):
        """Wait until a slot is available."""
        start = datetime.now()
        while self.get_available_count() == 0:
            if timeout and (datetime.now() - start).total_seconds() > timeout:
                raise TimeoutError("Timeout waiting for available agent slot")
            await asyncio.sleep(0.5)
