from random import randint
from typing import Tuple, List

from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk import account, encoding

from pyteal import compileTeal, Mode

from .account import Account
from .contracts import approval_program, clear_state_program
from .util import (
    waitForTransaction,
    fullyCompileContract,
    getAppGlobalState, getBalances,
)

APPROVAL_PROGRAM = b""
CLEAR_STATE_PROGRAM = b""

def getContracts(client: AlgodClient) -> Tuple[bytes, bytes]:
    """Get the compiled TEAL contracts for the amm.

    Args:
        client: An algod client that has the ability to compile TEAL programs.

    Returns:
        A tuple of 2 byte strings. The first is the approval program, and the
        second is the clear state program.
    """
    global APPROVAL_PROGRAM
    global CLEAR_STATE_PROGRAM

    if len(APPROVAL_PROGRAM) == 0:
        APPROVAL_PROGRAM = fullyCompileContract(client, approval_program())
        CLEAR_STATE_PROGRAM = fullyCompileContract(client, clear_state_program())

    return APPROVAL_PROGRAM, CLEAR_STATE_PROGRAM


def createAmmApp(
    client: AlgodClient,
    sender: Account,
    tokenA: int,
    tokenB: int,
    poolToken: int,
    feeBps: int,
    minIncrement: int,
) -> int:
    """Create a new amm.

    Args:
        client: An algod client.
        sender: The account that will create the amm application.
        tokenA: The id of token A in the liquidity pool,
        tokenB: The id of token A in the liquidity pool,
        poolToken: The id of pool token
        feeBps: The basis point fee to be charged per swap

    Returns:
        The ID of the newly created amm app.
    """
    approval, clear = getContracts(client)

    # tokenA, tokenB, poolToken, fee
    globalSchema = transaction.StateSchema(num_uints=7, num_byte_slices=1)
    localSchema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    app_args = [
        encoding.decode_address(sender.getAddress()),
        tokenA.to_bytes(8, "big"),
        tokenB.to_bytes(8, "big"),
        poolToken.to_bytes(8, "big"),
        feeBps.to_bytes(8, "big"),
        minIncrement.to_bytes(8, "big")
    ]

    txn = transaction.ApplicationCreateTxn(
        sender=sender.getAddress(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=globalSchema,
        local_schema=localSchema,
        app_args=app_args,
        sp=client.suggested_params(),
    )

    signedTxn = txn.sign(sender.getPrivateKey())

    client.send_transaction(signedTxn)

    response = waitForTransaction(client, signedTxn.get_txid())
    assert response.applicationIndex is not None and response.applicationIndex > 0
    return response.applicationIndex


def setupAmmApp(
    client: AlgodClient,
    appID: int,
    funder: Account,
    tokenA: int,
    tokenB: int,
    poolToken,
    poolTokenQty
) -> None:
    """Finish setting up an amm.

    This operation funds the pool account opts that account into
    both tokens and pool token, and sends the NFT to the escrow account, all in one atomic
    transaction group. The auction must not have started yet.

    The escrow account requires a total of 0.203 Algos for funding. See the code
    below for a breakdown of this amount.

    Args:
        client: An algod client.
        appID: The app ID of the auction.
        funder: The account providing the funding for the escrow account.
        tokenA: Token A id.
        tokenB: Token B id.
        poolToken: Pool token id.
    """
    appAddr = get_application_address(appID)

    suggestedParams = client.suggested_params()

    fundingAmount = (
        # min account balance
        100_000
        # additional min balance to opt into tokens
        + 100_000 * 3
        # 1000 * min txn fee
        + 1_000 * 1_000
    )

    fundAppTxn = transaction.PaymentTxn(
        sender=funder.getAddress(),
        receiver=appAddr,
        amt=fundingAmount,
        sp=suggestedParams,
    )

    setupTxn = transaction.ApplicationCallTxn(
        sender=funder.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"setup"],
        foreign_assets=[tokenA, tokenB, poolToken],
        sp=suggestedParams,
    )
    fundPoolTokenTxn = transaction.AssetTransferTxn(
        sender=funder.getAddress(),
        receiver=appAddr,
        index=poolToken,
        amt=poolTokenQty,
        sp=suggestedParams,
    )
    transaction.assign_group_id([fundAppTxn, setupTxn, fundPoolTokenTxn])

    signedFundAppTxn = fundAppTxn.sign(funder.getPrivateKey())
    signedSetupTxn = setupTxn.sign(funder.getPrivateKey())
    signedPoolTokenTxn = fundPoolTokenTxn.sign(funder.getPrivateKey())

    client.send_transactions([signedFundAppTxn, signedSetupTxn, signedPoolTokenTxn])

    waitForTransaction(client, signedFundAppTxn.get_txid())

def supply(client: AlgodClient, appID: int, qA: int, qB: int, supplier: Account) -> None:
    """Supply liquidity to the pool.
    Supplier should receive pool tokens proportional to their liquidity share in the pool.

    Args:
        client: AlgodClient,
        appID: amm app id,
        qA: quantity of token A to supply the pool
        qB: quantity of token B to supply to the pool
        supplier: supplier account
    """
    appAddr = get_application_address(appID)
    appGlobalState = getAppGlobalState(client, appID)
    suggestedParams = client.suggested_params()

    tokenA = appGlobalState[b"token_a_key"]
    tokenB = appGlobalState[b"token_b_key"]
    poolToken = appGlobalState[b"pool_token_key"]

    tokenATxn = transaction.AssetTransferTxn(
        sender=supplier.getAddress(),
        receiver=appAddr,
        index=tokenA,
        amt=qA,
        sp=suggestedParams,
    )
    tokenBTxn = transaction.AssetTransferTxn(
        sender=supplier.getAddress(),
        receiver=appAddr,
        index=tokenB,
        amt=qB,
        sp=suggestedParams,
    )

    appCallTxn = transaction.ApplicationCallTxn(
        sender=supplier.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"supply"],
        foreign_assets=[tokenA, tokenB, poolToken],
        sp=suggestedParams,
    )

    transaction.assign_group_id([tokenATxn, tokenBTxn, appCallTxn])
    signedTokenATxn = tokenATxn.sign(supplier.getPrivateKey())
    signedTokenBTxn = tokenBTxn.sign(supplier.getPrivateKey())
    signedAppCallTxn = appCallTxn.sign(supplier.getPrivateKey())

    client.send_transactions([signedTokenATxn, signedTokenBTxn, signedAppCallTxn])
    waitForTransaction(client, signedAppCallTxn.get_txid())

def withdraw(client: AlgodClient, appID: int, poolTokenAmount: int, withdrawAccount: Account) -> None:
    """Withdraw liquidity  + rewards from the pool back to supplier.
    Supplier should receive tokenA, tokenB + rewards proportional to the liquidity share in the pool they choose to withdraw.

    Args:
        client: AlgodClient,
        appID: amm app id,
        poolTokenAmount: pool token quantity,
        withdrawAccount: supplier account,
    """
    appAddr = get_application_address(appID)
    appGlobalState = getAppGlobalState(client, appID)
    suggestedParams = client.suggested_params()

    tokenA = appGlobalState[b"token_a_key"]
    tokenB = appGlobalState[b"token_b_key"]
    poolToken = appGlobalState[b"pool_token_key"]

    poolTokenTxn = transaction.AssetTransferTxn(
        sender=withdrawAccount.getAddress(),
        receiver=appAddr,
        index=poolToken,
        amt=poolTokenAmount,
        sp=suggestedParams,
    )

    appCallTxn = transaction.ApplicationCallTxn(
        sender=withdrawAccount.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"withdraw"],
        foreign_assets=[tokenA, tokenB, poolToken],
        sp=suggestedParams,
    )

    transaction.assign_group_id([poolTokenTxn, appCallTxn])
    signedPoolTokenTxn = poolTokenTxn.sign(withdrawAccount.getPrivateKey())
    signedAppCallTxn = appCallTxn.sign(withdrawAccount.getPrivateKey())

    client.send_transactions([signedPoolTokenTxn, signedAppCallTxn])
    waitForTransaction(client, signedAppCallTxn.get_txid())

def trade(client: AlgodClient, appID: int, tokenId: int, amount: int, trader: Account):
    """Trade tokenId token for the other token in the pool
    This action can only happen if there is liquidity in the pool
    If the trader sends token A, the pool fee is taken out from returned token B
    If the trader sends token B, the pool fee is taken out of sent token B before performing the swap
    """
    appAddr = get_application_address(appID)
    appGlobalState = getAppGlobalState(client, appID)
    suggestedParams = client.suggested_params()

    tokenA = appGlobalState[b"token_a_key"]
    tokenB = appGlobalState[b"token_b_key"]

    tradeTxn = transaction.AssetTransferTxn(
        sender=trader.getAddress(),
        receiver=appAddr,
        index=tokenId,
        amt=amount,
        sp=suggestedParams,
    )

    appCallTxn = transaction.ApplicationCallTxn(
        sender=trader.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"trade"],
        foreign_assets=[tokenA, tokenB],
        sp=suggestedParams,
    )

    transaction.assign_group_id([tradeTxn, appCallTxn])
    signedTradeTxn = tradeTxn.sign(trader.getPrivateKey())
    signedAppCallTxn = appCallTxn.sign(trader.getPrivateKey())

    client.send_transactions([signedTradeTxn, signedAppCallTxn])
    waitForTransaction(client, signedAppCallTxn.get_txid())

def closeAmm(client: AlgodClient, appID: int, closer: Account):
    """Close an amm.

    This action can only happen if there is no liquidity in the pool (outstanding pool tokens = 0).

    Args:
        client: An Algod client.
        appID: The app ID of the auction.
        closer: any account
    """
    appGlobalState = getAppGlobalState(client, appID)

    nftID = appGlobalState[b"nft_id"]

    accounts: List[str] = [encoding.encode_address(appGlobalState[b"seller"])]

    if any(appGlobalState[b"bid_account"]):
        # if "bid_account" is not the zero address
        accounts.append(encoding.encode_address(appGlobalState[b"bid_account"]))

    deleteTxn = transaction.ApplicationDeleteTxn(
        sender=closer.getAddress(),
        index=appID,
        accounts=accounts,
        foreign_assets=[nftID],
        sp=client.suggested_params(),
    )
    signedDeleteTxn = deleteTxn.sign(closer.getPrivateKey())

    client.send_transaction(signedDeleteTxn)

    waitForTransaction(client, signedDeleteTxn.get_txid())
