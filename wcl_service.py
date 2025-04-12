import os
import httpx
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from dotenv import load_dotenv
import schemas
import logging

load_dotenv()

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # EXPLICITLY SET LEVEL
# Optional: Add a handler if running standalone, but Uvicorn should handle it
# handler = logging.StreamHandler()
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# handler.setFormatter(formatter)
# logger.addHandler(handler)

WCL_CLIENT_ID = os.getenv("WCL_CLIENT_ID")
WCL_CLIENT_SECRET = os.getenv("WCL_CLIENT_SECRET")
WCL_OAUTH_URL = "https://www.warcraftlogs.com/oauth/token"
WCL_API_V2_URL = "https://www.warcraftlogs.com/api/v2/client"

# Simple in-memory cache for the token
_token_cache = {
    "access_token": None,
    "expires_at": None
}

def is_token_valid():
    """Check if the cached token is still valid."""
    return _token_cache["access_token"] and \
           _token_cache["expires_at"] and \
           _token_cache["expires_at"] > datetime.now(timezone.utc)

async def get_access_token():
    """Get a valid access token, either from cache or by requesting a new one."""
    if is_token_valid():
        return _token_cache["access_token"]

    if not WCL_CLIENT_ID or not WCL_CLIENT_SECRET:
        raise ValueError("WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set in .env file")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                WCL_OAUTH_URL,
                data={"grant_type": "client_credentials"},
                auth=(WCL_CLIENT_ID, WCL_CLIENT_SECRET)
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            token_data = response.json()

            _token_cache["access_token"] = token_data["access_token"]
            expires_in = token_data["expires_in"] # seconds
            _token_cache["expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60) # Refresh a bit early

            print("Successfully obtained new WCL API token.") # Add logging
            return _token_cache["access_token"]
        except httpx.RequestError as exc:
            print(f"An error occurred while requesting {exc.request.url!r}: {exc}")
            raise
        except httpx.HTTPStatusError as exc:
            print(f"Error response {exc.response.status_code} while requesting {exc.request.url!r}: {exc.response.text}")
            raise

def extract_report_code(report_url: str) -> str | None:
    """Extracts the report code from a Warcraft Logs URL."""
    try:
        parsed_url = urlparse(report_url)
        path_parts = parsed_url.path.strip('/').split('/')
        # Expecting format like /reports/<code>
        if len(path_parts) >= 2 and path_parts[0] == 'reports':
            return path_parts[1]
    except Exception as e:
        print(f"Error parsing report URL '{report_url}': {e}")
    return None

async def fetch_fight_tables(report_code: str, fight_id: int) -> dict:
    """Fetches damage and healing tables for a specific fight ID."""
    graphql_query = """
    query FightTables($reportCode: String!, $fightIDs: [Int!]!) {
        reportData {
            report(code: $reportCode) {
                damageTable: table(dataType: DamageDone, fightIDs: $fightIDs)
                healingTable: table(dataType: Healing, fightIDs: $fightIDs)
            }
        }
    }
    """
    variables = {"reportCode": report_code, "fightIDs": [fight_id]}
    token = await get_access_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                WCL_API_V2_URL,
                json={"query": graphql_query, "variables": variables},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error(f"GraphQL error fetching fight tables for fight {fight_id}: {data['errors']}")
                return None

            report_data = data.get("data", {}).get("reportData", {}).get("report", {})
            logger.debug(f"WCL_SERVICE: Fetched tables for fight {fight_id}: {report_data}")
            return report_data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching fight tables for fight {fight_id}: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error fetching fight tables for fight {fight_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching fight tables for fight {fight_id}: {e}")
            return None


async def fetch_report_data(report_code: str) -> dict:
    """Fetches report metadata, fights, and then damage/healing tables per boss fight."""
    # Initial query for metadata and fights list
    graphql_query_metadata = """
    query ReportMetadataAndFights($reportCode: String!) {
        reportData {
            report(code: $reportCode) {
                code
                title
                owner { name }
                startTime
                endTime
                zone { id name }
                fights(translate: true) {
                  id
                  startTime
                  endTime
                  name
                  encounterID
                }
             }
         }
     }
    """
    variables = {"reportCode": report_code}
    token = await get_access_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            # --- First request: Get Metadata and Fights --- 
            logger.debug(f"WCL_SERVICE: Fetching metadata and fights for report {report_code}")
            response = await client.post(
                WCL_API_V2_URL,
                json={"query": graphql_query_metadata, "variables": variables},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error(f"GraphQL error fetching metadata/fights: {data['errors']}")
                return None

            report_info = data.get("data", {}).get("reportData", {}).get("report", {})
            if not report_info:
                logger.error("Could not extract report info from WCL response.")
                return None

            logger.debug(f"Extracted report_info structure (metadata/fights): {report_info}")

            # Extract report metadata
            report_metadata = {
                "code": report_info.get("code"),
                "title": report_info.get("title"),
                "owner": report_info.get("owner", {}).get("name"),
                # Return raw WCL timestamps (milliseconds)
                "startTime": report_info.get("startTime"), 
                "endTime": report_info.get("endTime"),   
                "zone_id": report_info.get("zone", {}).get("id"),
                "zone_name": report_info.get("zone", {}).get("name"),
                # Include the raw fights list needed by the main processing logic
                "fights": report_info.get("fights", []) 
            }
            logger.debug(f"WCL_SERVICE: Extracted report metadata: {report_metadata}")

            # Extract fights list (used for subsequent table fetches)
            fights_list = report_info.get("fights", []) # Keep this local variable too
            logger.debug(f"WCL_SERVICE: Extracted {len(fights_list)} fights for table fetching.")

            # --- Subsequent requests: Get Tables per Boss Fight --- 
            fight_specific_data = {}
            boss_fight_count = 0

            for fight in fights_list:
                fight_id = fight.get("id")
                is_boss_fight = fight.get("encounterID", 0) != 0 # encounterID=0 means trash
                fight_name = fight.get("name")

                if is_boss_fight and fight_id:
                    boss_fight_count += 1
                    logger.info(f"WCL_SERVICE: Fetching data for Boss Fight ID: {fight_id}, Name: {fight_name}")
                    # Fetch damage/healing tables for this specific boss fight
                    fight_tables = await fetch_fight_tables(report_code, fight_id)
                    
                    if fight_tables:
                        # Process and store fight-specific data (placeholder logic)
                        # TODO: Adapt downstream processing (crud.py, models.py) for this structure
                        fight_specific_data[fight_id] = {
                            "name": fight_name,
                            "damageTable": fight_tables.get("damageTable"),
                            "healingTable": fight_tables.get("healingTable")
                        }
                        logger.debug(f"WCL_SERVICE: Successfully stored data for fight {fight_id}")
                    else:
                        logger.warning(f"WCL_SERVICE: Failed to fetch tables for boss fight {fight_id}. Skipping.")
            
            logger.info(f"WCL_SERVICE: Fetched data for {boss_fight_count} boss fights.")
            logger.debug(f"WCL_SERVICE: Aggregated fight-specific data: {fight_specific_data}") # Log the final structure for now

            # Combine metadata and processed fight data (adjust structure as needed)
            # For now, return metadata and the new fight_specific_data dict
            # The downstream processing logic needs to be updated to handle this new structure
            return {
                "metadata": report_metadata,
                "fight_data": fight_specific_data 
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error during report processing: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error during report processing: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error during report processing: {e}") # Use exception for stack trace
            return None
