"""Feedback store for learning from manual review decisions."""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from ..models.db_models import MappingRule
from ..utils.helpers import generate_uuid


class FeedbackStoreService:
    def get_rules(
        self,
        db: Session,
        hotel_id: Optional[str] = None,
        rule_type: Optional[str] = None,
        source_platform: Optional[str] = None,
    ) -> List[MappingRule]:
        query = db.query(MappingRule)
        if hotel_id:
            query = query.filter(
                (MappingRule.hotel_id == hotel_id) | (MappingRule.hotel_id.is_(None))
            )
        if rule_type:
            query = query.filter(MappingRule.rule_type == rule_type)
        if source_platform:
            query = query.filter(
                (MappingRule.source_platform == source_platform) | (MappingRule.source_platform.is_(None))
            )
        return query.order_by(MappingRule.confidence.desc()).all()

    def add_rule(
        self,
        db: Session,
        rule_type: str,
        source_value: str,
        target_value: str,
        source_platform: Optional[str] = None,
        hotel_id: Optional[str] = None,
        confidence: float = 1.0,
        created_from: str = "user_feedback",
    ) -> MappingRule:
        # Check for duplicate
        existing = db.query(MappingRule).filter(
            MappingRule.rule_type == rule_type,
            MappingRule.source_value == source_value,
            MappingRule.source_platform == source_platform,
        ).first()
        if existing:
            existing.target_value = target_value
            existing.confidence = max(existing.confidence, confidence)
            db.commit()
            return existing

        rule = MappingRule(
            id=generate_uuid(),
            hotel_id=hotel_id,
            rule_type=rule_type,
            source_platform=source_platform,
            source_value=source_value,
            target_value=target_value,
            confidence=confidence,
            created_from=created_from,
        )
        db.add(rule)
        db.commit()
        return rule

    def delete_rule(self, rule_id: str, db: Session) -> bool:
        rule = db.query(MappingRule).filter(MappingRule.id == rule_id).first()
        if not rule:
            return False
        db.delete(rule)
        db.commit()
        return True

    def lookup_room_type(
        self,
        raw_value: str,
        db: Session,
        platform: Optional[str] = None,
        hotel_id: Optional[str] = None,
    ) -> Optional[str]:
        normalized = raw_value.lower().strip()
        query = db.query(MappingRule).filter(
            MappingRule.rule_type == "room_type",
            MappingRule.source_value == normalized,
        )
        if platform:
            query = query.filter(
                (MappingRule.source_platform == platform) | (MappingRule.source_platform.is_(None))
            )
        rule = query.order_by(MappingRule.confidence.desc()).first()
        return rule.target_value if rule else None

    def seed_from_config(self, config: Dict[str, Any], db: Session) -> int:
        """Seed the DB with rules from the room_type_mapping.json config."""
        count = 0
        for mapping in config.get("room_type_mappings", []):
            self.add_rule(
                db=db,
                rule_type="room_type",
                source_value=mapping["source_value"].lower(),
                target_value=mapping["normalized"],
                source_platform=mapping.get("platform"),
                confidence=1.0,
                created_from="seed",
            )
            count += 1

        for platform, mappings in config.get("status_mappings", {}).items():
            for source, target in mappings.items():
                self.add_rule(
                    db=db,
                    rule_type="status",
                    source_value=source,
                    target_value=target,
                    source_platform=platform,
                    confidence=1.0,
                    created_from="seed",
                )
                count += 1

        return count
