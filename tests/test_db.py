"""
Test database models and repository functions.
"""
import pytest
import uuid
from db.database import init_db, get_session
from db import models, repository
from miniapp.auth import hash_password


@pytest.fixture(scope="module")
def setup_db():
    """Initialize test database"""
    init_db()
    yield


class TestDatabaseModels:
    """Test database models"""
    
    def test_create_company(self, setup_db):
        """Test creating a company"""
        unique_mc = str(uuid.uuid4().int)[:6]  # Unique MC number
        unique_prefix = f"T{unique_mc[:4]}"
        
        with get_session() as session:
            company = models.Company(
                mc_number=unique_mc,
                company_name=f"Test Company {unique_mc}",
                telegram_group_prefix=unique_prefix,
                password_hash=hash_password("testpass123")
            )
            session.add(company)
            session.commit()
            session.refresh(company)
            
            assert company.id > 0
            assert company.mc_number == unique_mc
            assert company.password_hash is not None


class TestRepository:
    """Test repository functions"""
    
    def test_get_company_by_mc(self, setup_db):
        """Test getting company by MC number"""
        unique_mc = str(uuid.uuid4().int)[:6]
        unique_prefix = f"T{unique_mc[:4]}"
        
        # First create a test company
        with get_session() as session:
            company = models.Company(
                mc_number=unique_mc,
                company_name=f"Test Company {unique_mc}",
                telegram_group_prefix=unique_prefix,
                password_hash=hash_password("pass123")
            )
            session.add(company)
            session.commit()
        
        # Test repository function
        result = repository.get_company_by_mc(unique_mc)
        assert result is not None
        assert result.mc_number == unique_mc
    
    def test_get_nonexistent_company(self, setup_db):
        """Test getting non-existent company"""
        result = repository.get_company_by_mc("NOTEXIST999")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
