"""
洛谷数据模型定义
"""
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class LuoguUser(BaseModel):
    """洛谷用户账号信息"""
    qq_id: str = Field(..., description="QQ用户ID")
    luogu_uid: Optional[str] = Field(None, description="洛谷UID")
    username: str = Field(..., description="登录用户名(手机号/邮箱)")
    password: str = Field(..., description="登录密码")
    bind_time: datetime = Field(default_factory=datetime.now, description="绑定时间")


class LuoguCookie(BaseModel):
    """洛谷登录Cookie"""
    user_id: str = Field(..., description="洛谷用户ID")
    cookies: List[Dict[str, Any]] = Field(default_factory=list, description="Cookie列表")
    earliest_date: date = Field(..., description="最早登录日期")
    recent_date: date = Field(..., description="最近登录日期")


class UserProfile(BaseModel):
    """洛谷用户主页数据"""
    uid: str
    username: str
    nickname: str
    rank: str  # 排名
    rating: Optional[int] = None  # 比赛Rating
    rating_rank: Optional[int] = None
    solved_count: int = 0  # 已解决题目数
    total_submissions: int = 0  # 总提交数
    ac_rate: float = 0.0  # AC率
    register_time: Optional[str] = None
    bio: Optional[str] = None


class SubmissionTrend(BaseModel):
    """做题趋势数据"""
    uid: str
    date: str  # YYYY-MM-DD
    count: int  # 当日做题数
    heatmap_url: Optional[str] = None  # 趋势图URL


class GuzhiInfo(BaseModel):
    """咕值信息"""
    uid: str
    total: float = 0.0       # 总咕值
    basic: float = 0.0      # 基础信用
    practice: float = 0.0   # 练习情况
    contest: float = 0.0    # 比赛情况
    social: float = 0.0     # 社区贡献
    prize: float = 0.0      # 获得成就
    trend: List[float] = Field(default_factory=list)
    categories: Dict[str, float] = Field(default_factory=dict)


class RatingTrend(BaseModel):
    """Rating趋势"""
    uid: str
    dates: List[str] = Field(default_factory=list)
    ratings: List[int] = Field(default_factory=list)
    chart_url: Optional[str] = None


class RecentProblems(BaseModel):
    """最近做题记录"""
    uid: str
    problems: List[Dict[str, Any]] = Field(default_factory=list)
    # 每个题目包含: pid, title, status(通过/尝试中), submit_time


class LuoguUserData(BaseModel):
    """用户完整数据"""
    user: UserProfile
    guzhi: Optional[GuzhiInfo] = None
    rating_trend: Optional[RatingTrend] = None
    recent_problems: Optional[RecentProblems] = None
    last_update: datetime = Field(default_factory=datetime.now)


class ContestHistory(BaseModel):
    """比赛历史"""
    uid: str
    contests: List[Dict[str, Any]] = Field(default_factory=list)
    # 每个比赛包含: date, rating, change, contest_name


class ProblemDetail(BaseModel):
    """题目详情"""
    pid: str
    difficulty: int
    difficulty_name: str
    passed: bool


class PracticeData(BaseModel):
    """练习数据"""
    uid: str
    total_passed: int = 0
    total_unpassed: int = 0
    passed_problems: List[str] = Field(default_factory=list)
    unpassed_problems: List[str] = Field(default_factory=list)
    passed_by_difficulty: Dict[str, List[str]] = Field(default_factory=dict)
    unpassed_by_difficulty: Dict[str, List[str]] = Field(default_factory=dict)
    difficulty_stats: Dict[str, int] = Field(default_factory=dict)
    passed_details: List[Dict[str, Any]] = Field(default_factory=list)
    unpassed_details: List[Dict[str, Any]] = Field(default_factory=list)
