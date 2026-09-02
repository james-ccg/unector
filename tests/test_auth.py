"""
Tests for authentication and JWT tokens.
"""
import pytest
from miniapp.auth import hash_password, verify_password, create_token, decode_token


class TestPasswordHashing:
    """Test password hashing functions"""
    
    def test_hash_password(self):
        """Test password hashing"""
        password = "mySecurePassword123"
        hashed = hash_password(password)
        
        assert hashed != password
        assert len(hashed) > 20
        assert hashed.startswith("$2b$")
    
    def test_verify_correct_password(self):
        """Test verifying correct password"""
        password = "correctPassword"
        hashed = hash_password(password)
        
        assert verify_password(password, hashed) is True
    
    def test_verify_wrong_password(self):
        """Test verifying wrong password"""
        password = "correctPassword"
        hashed = hash_password(password)
        
        assert verify_password("wrongPassword", hashed) is False
    
    def test_verify_invalid_hash(self):
        """Test verifying with invalid hash"""
        assert verify_password("password", "invalid_hash") is False


class TestJWTTokens:
    """Test JWT token functions"""
    
    def test_create_token(self):
        """Test creating a token"""
        payload = {"role": "owner", "company_id": 1, "purpose": "session"}
        token = create_token(payload)
        
        assert isinstance(token, str)
        assert len(token) > 50
        assert "." in token  # JWT has dots
    
    def test_decode_valid_token(self):
        """Test decoding valid token"""
        payload = {"role": "dispatcher", "company_id": 5, "purpose": "session"}
        token = create_token(payload)
        decoded = decode_token(token)
        
        assert decoded is not None
        assert decoded["role"] == "dispatcher"
        assert decoded["company_id"] == 5
        assert "exp" in decoded
    
    def test_decode_invalid_token(self):
        """Test decoding invalid token"""
        invalid_token = "invalid.jwt.token"
        decoded = decode_token(invalid_token)
        
        assert decoded is None
    
    def test_token_contains_expiration(self):
        """Test that token contains expiration"""
        import time
        payload = {"user_id": 1, "purpose": "session"}
        token = create_token(payload)
        decoded = decode_token(token)
        
        assert "exp" in decoded
        assert decoded["exp"] > time.time()

    def test_token_without_a_purpose_is_refused(self):
        """A token with no purpose is accepted by whoever is least strict,
        so it cannot be minted at all - see miniapp/auth.py."""
        import pytest

        with pytest.raises(ValueError, match="purpose"):
            create_token({"role": "owner", "company_id": 1})

    def test_decode_rejects_a_token_minted_for_another_job(self):
        """The whole point of the purpose claim."""
        token = create_token({"company_id": 1, "purpose": "gmail_oauth"})

        assert decode_token(token, purpose="gmail_oauth") is not None
        assert decode_token(token, purpose="session") is None
        assert decode_token(token, purpose="2fa_login") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
